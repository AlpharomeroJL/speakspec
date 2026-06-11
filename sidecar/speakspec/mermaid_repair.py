"""Mermaid validate-and-repair loop (release blocker, Phase 5).

Order per diagram (per the build contract):

1. parse with the real Mermaid 11 parser (Node helper, see
   ``tools/mermaid-validate/validate.mjs``),
2. on failure, feed the exact parser error back to the model and regenerate
   (cap 3 retries),
3. then the deterministic sanitizer,
4. if still failing, emit a clean stub diagram flagged for manual review.

Before the first parse the source gets a lossless framing normalization only
(trim, strip accidental code fences, strip init/theme directives for theme
neutrality) — content is never altered without a failed parse.

If Node is unavailable at runtime the sanitizer still runs and diagrams are
marked ``unvalidated``; the webview's Mermaid renderer is the last-line check
there (documented in docs/architecture.md). The release gate corpus run
requires the real validator.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from speakspec.config import repo_root
from speakspec.messages import SidecarError

logger = logging.getLogger(__name__)

DIAGRAM_KINDS = ("sequence", "er", "component", "c4_context", "c4_container")

MAX_MODEL_REPAIRS = 3

REPAIR_SYSTEM_PROMPT = (
    "You rewrite invalid Mermaid 11 diagrams into valid Mermaid 11 syntax. "
    "Preserve the meaning — every participant, entity, node, relationship, and "
    "label — but express it in correct syntax for the required diagram type. "
    "Stay theme-neutral: no init or theme directives. Known hazards: missing or "
    "wrong diagram-type header, invented keywords, unescaped parentheses or "
    "double quotes inside node labels, fullwidth or Chinese punctuation, "
    "malformed arrows, reserved words like 'end' as bare node ids. Returning "
    "the source unchanged is a failure."
)

REPAIR_FORMAT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mermaid"],
    "properties": {"mermaid": {"type": "string"}},
}

# Per-kind syntax rules used by both the repair prompt and the deterministic
# header normalizer. Skeletons are known-valid Mermaid 11 (unit-tested).
KIND_RULES: dict[str, dict[str, str]] = {
    "sequence": {
        "header": "sequenceDiagram",
        "notes": "Messages are 'A->>B: label' (solid) or 'A-->>B: label' (reply). "
        "Declare participants first.",
        "skeleton": (
            "sequenceDiagram\n"
            "  participant User\n"
            "  participant System\n"
            "  User->>System: request\n"
            "  System-->>User: response"
        ),
    },
    "er": {
        "header": "erDiagram",
        "notes": "Entities are single words. Relationships: 'A ||--o{ B : label'. "
        "Attributes live inside braces as 'type name' lines. There is no "
        "'entity' or 'attribute' keyword.",
        "skeleton": (
            "erDiagram\n"
            "  CUSTOMER ||--o{ ORDER : places\n"
            "  CUSTOMER {\n"
            "    string name\n"
            "    string email\n"
            "  }"
        ),
    },
    "component": {
        "header": "graph TD",
        "notes": "Nodes are 'id[Label]'; edges are '-->'. Wrap labels containing "
        "parentheses or quotes in double quotes.",
        "skeleton": ('graph TD\n  api["API Server"] --> db[(Database)]\n  api --> queue[Queue]'),
    },
    "c4_context": {
        "header": "C4Context",
        "notes": 'Use only Person(alias, "Label"), System(alias, "Label"), '
        'System_Ext(alias, "Label"), and Rel(from, to, "label") calls.',
        "skeleton": (
            "C4Context\n"
            "  title System Context\n"
            '  Person(user, "User")\n'
            '  System(sys, "System", "What it does")\n'
            '  System_Ext(ext, "External Service")\n'
            '  Rel(user, sys, "Uses")\n'
            '  Rel(sys, ext, "Calls")'
        ),
    },
    "c4_container": {
        "header": "C4Container",
        "notes": 'Use only Person(), Container(alias, "Label", "tech"), '
        "ContainerDb(), System_Ext(), and Rel() calls.",
        "skeleton": (
            "C4Container\n"
            "  title Containers\n"
            '  Person(user, "User")\n'
            '  Container(web, "Web App", "framework", "Serves the UI")\n'
            '  ContainerDb(db, "Database", "SQLite", "Stores data")\n'
            '  Rel(user, web, "Uses", "HTTPS")\n'
            '  Rel(web, db, "Reads and writes")'
        ),
    },
}

STUBS = {
    "sequence": "sequenceDiagram\n  participant ManualReview as Diagram needs manual review",
    "er": "erDiagram\n  MANUAL_REVIEW {\n    string note\n  }",
    "component": 'graph TD\n  manual_review["Diagram needs manual review"]',
    "c4_context": (
        "C4Context\n"
        '  Person(reviewer, "Reviewer")\n'
        '  System(stub, "Diagram needs manual review")\n'
        '  Rel(reviewer, stub, "reviews")'
    ),
    "c4_container": (
        "C4Container\n"
        '  Person(reviewer, "Reviewer")\n'
        '  Container(stub, "Diagram needs manual review", "n/a")\n'
        '  Rel(reviewer, stub, "reviews")'
    ),
}

_FENCE_RE = re.compile(r"^```(?:mermaid)?\s*\n(.*?)\n?```\s*$", re.DOTALL)
_INIT_RE = re.compile(r"%%\{.*?\}%%\s*", re.DOTALL)

_FULLWIDTH = str.maketrans(
    {
        "（": "(",
        "）": ")",
        "：": ":",
        "，": ",",
        "。": ".",
        "；": ";",
        "、": ",",
        "！": "!",
        "？": "?",
        "“": "'",
        "”": "'",
        "‘": "'",
        "’": "'",
        "→": "-",
        "—": "-",
    }
)


def normalize_frame(source: str) -> str:
    """Lossless framing cleanup: fences, init directives, whitespace."""
    text = source.strip()
    fence = _FENCE_RE.match(text)
    if fence:
        text = fence.group(1).strip()
    text = _INIT_RE.sub("", text).strip()
    return text


def _diagram_family(source: str) -> str:
    """First meaningful token: 'graph', 'sequenceDiagram', 'erDiagram', ..."""
    for line in source.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("%%"):
            return stripped.split()[0] if stripped.split() else ""
    return ""


def _quote_hazardous_labels(text: str) -> str:
    """Wrap flowchart ``[...]`` labels containing parens/quotes in quotes."""

    def fix(match: re.Match[str]) -> str:
        label = match.group(1)
        if label.startswith('"') and label.endswith('"'):
            return match.group(0)
        if any(ch in label for ch in '()"'):
            return '["' + label.replace('"', "'") + '"]'
        return match.group(0)

    return re.sub(r"\[([^\[\]\n]*)\]", fix, text)


def _fix_header(text: str, kind: str) -> str:
    """Deterministically normalize the diagram-type header for ``kind``.

    The expected kind is known from the schema field, so a wrong or missing
    first token ("sequence", "er", "component", lowercase c4context, ...) can
    be replaced or prepended without guessing.
    """
    rules = KIND_RULES[kind]
    header = rules["header"]
    lines = text.splitlines()
    idx = next(
        (i for i, ln in enumerate(lines) if ln.strip() and not ln.strip().startswith("%%")),
        None,
    )
    if idx is None:
        return header
    first = lines[idx].strip()
    first_token = first.split()[0].rstrip(":").lower()
    already_ok = {
        "sequence": first.startswith("sequenceDiagram"),
        "er": first.startswith("erDiagram"),
        "component": first_token in ("graph", "flowchart"),
        "c4_context": first.startswith("C4Context"),
        "c4_container": first.startswith("C4Container"),
    }[kind]
    if already_ok:
        return text
    # A bare/wrong type token gets replaced; real content gets the header
    # prepended above it.
    wrong_tokens = {
        "sequence": {"sequence", "sequencediagram"},
        "er": {"er", "erd", "erdiagram", "entityrelationship"},
        "component": {"component", "componentdiagram", "graphtd", "diagram"},
        "c4_context": {"c4context", "c4", "context"},
        "c4_container": {"c4container", "container", "containerdiagram"},
    }[kind]
    if first_token in wrong_tokens and len(first.split()) <= 2:
        lines[idx] = header
    else:
        lines.insert(idx, header)
    return "\n".join(lines)


def _slug(name: str) -> str:
    """Mermaid-safe node id from a free-text name."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip()).strip("_").lower() or "node"
    if slug[0].isdigit():
        slug = f"n_{slug}"
    if slug == "end":  # reserved in flowcharts
        slug = "end_node"
    return slug


def _convert_er_dialect(text: str) -> str | None:
    """Convert the invented ``entity X / attribute y / A has B`` dialect.

    Small models consistently emit this pseudo-syntax for erDiagram. The
    conversion preserves entities, attributes (typed ``string`` since types
    are unknown), and explicit ``A has B`` relationships. Returns None when
    the dialect is not present.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not any(re.match(r"^entity\s+\w", ln, re.I) for ln in lines):
        return None
    entities: dict[str, list[str]] = {}
    relations: list[tuple[str, str, str]] = []
    current: str | None = None
    for ln in lines:
        if m := re.match(r"^entity\s+(.+)$", ln, re.I):
            current = _slug(m.group(1)).upper()
            entities.setdefault(current, [])
        elif m := re.match(r"^attribute\s+(.+)$", ln, re.I):
            if current is not None:
                entities[current].append(_slug(m.group(1)))
        elif m := re.match(r"^(\w[\w ]*?)\s+has(?:\s+many)?\s+(\w[\w ]*)$", ln, re.I):
            relations.append((_slug(m.group(1)).upper(), _slug(m.group(2)).upper(), "has"))
        elif m := re.match(r"^(\w[\w ]*?)\s*[-=]+>{1,2}\s*(\w[\w ]*?)\s*$", ln):
            relations.append((_slug(m.group(1)).upper(), _slug(m.group(2)).upper(), "has"))
    if not entities:
        return None
    out = ["erDiagram"]
    for left, right, label in relations:
        out.append(f"  {left} ||--o{{ {right} : {label}")
    for name, attrs in entities.items():
        if attrs:
            out.append(f"  {name} {{")
            out.extend(f"    string {a}" for a in attrs)
            out.append("  }")
        elif not any(name in (r[0], r[1]) for r in relations):
            # Bare entity with no attributes/relations still must appear.
            out.append(f"  {name} {{")
            out.append("    string id")
            out.append("  }")
    return "\n".join(out)


def _convert_flowchart_dialect(text: str) -> str:
    """Normalize pseudo-flowchart lines into valid ``graph TD`` syntax.

    Handles the recurring failure shapes: ``component X`` declarations,
    multi-word bare node names, and sequence-style ``A --> B: label`` edges.
    """
    body: list[str] = []
    declared: dict[str, str] = {}

    def node_ref(name: str) -> str:
        name = name.strip()
        slug = _slug(name)
        if slug not in declared:
            declared[slug] = name
            safe = name.replace('"', "'")
            return f'{slug}["{safe}"]'
        return slug

    for raw in text.splitlines():
        ln = raw.strip()
        if not ln or ln.startswith("%%"):
            continue
        # Bare header lines only — never 'component <Name>' declarations.
        if re.match(r"^(graph|flowchart)(\s+\w{2})?$|^(componentDiagram|component)$", ln, re.I):
            continue
        if m := re.match(r"^component\s+(.+)$", ln, re.I):
            body.append(f"  {node_ref(m.group(1))}")
            continue
        if m := re.match(r"^(.+?)\s*[-=]+>{1,2}\s*([^:|\[\]]+?)(?:\s*:\s*(.+))?$", ln):
            left, right, label = m.group(1), m.group(2), m.group(3)
            if "[" in left or "[" in right or "|" in ln:
                body.append(f"  {ln}")
                continue
            if label:
                safe_label = label.strip().replace('"', "'")
                edge = f'-->|"{safe_label}"|'  # quoted: labels may contain parens
            else:
                edge = "-->"
            body.append(f"  {node_ref(left)} {edge} {node_ref(right)}")
            continue
        # A line that is just a name (no arrows, no mermaid syntax) becomes a
        # declared node — bare multi-word names are invalid otherwise.
        if not re.search(
            r"-->|---|==>|\[|\]|\{|\}|\bsubgraph\b|\bend\b|\bstyle\b|\bclassDef\b", ln
        ) and re.match(r"^[\w(][\w ()./&'-]*$", ln):
            body.append(f"  {node_ref(ln)}")
            continue
        body.append(f"  {ln}")
    return "graph TD\n" + "\n".join(body) if body else "graph TD"


def _convert_c4_dialect(text: str, kind: str) -> str | None:
    """Convert ``system X / user X / external X / container X`` pseudo-C4.

    Builds Person/System/System_Ext/Container declarations plus Rel() lines
    for ``A uses B``-style statements between declared elements. Returns None
    when the dialect is not present.
    """
    header = "C4Context" if kind == "c4_context" else "C4Container"
    decl_re = re.compile(
        r"^(system|user|person|actor|external|ext|container|database|db)\s*:?\s+(.+)$", re.I
    )
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not any(decl_re.match(ln) for ln in lines):
        return None
    decls: list[str] = []
    alias_by_name: dict[str, str] = {}

    def declare(role: str, name: str) -> None:
        name = name.strip().rstrip(".")
        alias = _slug(name)
        if name.lower() in alias_by_name:
            return
        alias_by_name[name.lower()] = alias
        safe = name.replace('"', "'")
        if role in ("user", "person", "actor"):
            decls.append(f'  Person({alias}, "{safe}")')
        elif role in ("external", "ext"):
            decls.append(f'  System_Ext({alias}, "{safe}")')
        elif role in ("container",) or (kind == "c4_container" and role == "system"):
            decls.append(f'  Container({alias}, "{safe}", "n/a")')
        elif role in ("database", "db"):
            decls.append(f'  ContainerDb({alias}, "{safe}", "n/a")')
        else:
            decls.append(f'  System({alias}, "{safe}")')

    rels: list[str] = []
    rel_re = re.compile(
        r"^(.+?)\s+(uses|calls|sends to|exports to|reads|writes|notifies)\s+(.+)$", re.I
    )
    arrow_re = re.compile(r"^(.+?)\s*[-=]+>{1,2}\s*(.+?)(?:\s*:\s*(.+))?$")
    for ln in lines:
        if m := decl_re.match(ln):
            declare(m.group(1).lower(), m.group(2))
    for ln in lines:
        if decl_re.match(ln):
            continue
        verb = "uses"
        if m := rel_re.match(ln):
            left, verb, right = m.group(1), m.group(2), m.group(3)
        elif m := arrow_re.match(ln):
            left, right = m.group(1), m.group(2)
            verb = m.group(3) or "uses"
        else:
            continue
        a = alias_by_name.get(left.strip().rstrip(".").lower())
        b = alias_by_name.get(right.strip().rstrip(".").lower())
        if a and b:
            safe_verb = verb.strip().replace('"', "'")
            rels.append(f'  Rel({a}, {b}, "{safe_verb}")')
    if not decls:
        return None
    return "\n".join([header, *decls, *rels])


def sanitize(source: str, kind: str | None = None) -> str:
    """Deterministic last-resort fixes for the known LLM failure modes."""
    text = normalize_frame(source).translate(_FULLWIDTH)
    # Structural converters for the recurring small-model pseudo-dialects.
    if kind == "er":
        converted = _convert_er_dialect(text)
        if converted is not None:
            return converted
    if kind in ("c4_context", "c4_container"):
        converted = _convert_c4_dialect(text, kind)
        if converted is not None:
            return converted
    if kind in KIND_RULES:
        text = _fix_header(text, kind)
    family = _diagram_family(text)
    if family in ("graph", "flowchart"):
        if kind == "component":
            text = _convert_flowchart_dialect(text)
        text = _quote_hazardous_labels(text)
        # Standalone -> or => become valid flowchart arrows.
        text = re.sub(r"(?<![-<>=])->(?!>)", "-->", text)
        text = re.sub(r"(?<![=<>-])=>(?!>)", "-->", text)
        # 'end' is reserved as a bare node id in flowcharts.
        text = re.sub(r"^(\s*)end(\s*(?:-->|---|\[))", r"\1end_node\2", text, flags=re.MULTILINE)
    return text


class MermaidValidator:
    """Persistent Node subprocess wrapping the real Mermaid 11 parser."""

    def __init__(self, node: str | None = None, script: Path | None = None) -> None:
        """Resolve the node binary and validator script (env-overridable)."""
        self._node = node or os.environ.get("SPEAKSPEC_NODE") or shutil.which("node")
        env_script = os.environ.get("SPEAKSPEC_MERMAID_VALIDATOR")
        self._script = script or (
            Path(env_script)
            if env_script
            else repo_root() / "tools" / "mermaid-validate" / "validate.mjs"
        )
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._next_id = 0

    @property
    def available(self) -> bool:
        """Whether a real parser can run on this machine."""
        return bool(self._node) and self._script.is_file()

    def _ensure_proc(self) -> subprocess.Popen[str]:
        """Spawn (or respawn) the validator service and wait for readiness."""
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        if not self.available:
            raise SidecarError(
                "mermaid-validator-unavailable",
                "Node.js was not found, so Mermaid sources cannot be parse-checked "
                "on this machine. Diagrams will be sanitized and validated by the "
                "app's renderer instead.",
            )
        creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        self._proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [str(self._node), str(self._script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            cwd=str(self._script.parent),
            creationflags=creationflags,
        )
        ready = self._proc.stdout.readline() if self._proc.stdout else ""
        if "__ready__" not in ready:
            raise SidecarError(
                "mermaid-validator-unavailable",
                "The Mermaid validator service failed to start.",
                {"first_line": ready[:200]},
            )
        return self._proc

    def check(self, source: str) -> dict[str, Any]:
        """Parse ``source``; return ``{ok, error?, diagramType?}``."""
        with self._lock:
            proc = self._ensure_proc()
            self._next_id += 1
            req_id = f"v{self._next_id}"
            assert proc.stdin is not None and proc.stdout is not None  # noqa: S101
            proc.stdin.write(json.dumps({"id": req_id, "source": source}) + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
        if not line:
            self._proc = None
            raise SidecarError(
                "mermaid-validator-unavailable", "The Mermaid validator service exited."
            )
        return json.loads(line)

    def close(self) -> None:
        """Terminate the service process if running."""
        if self._proc is not None and self._proc.poll() is None:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
            self._proc.terminate()
        self._proc = None


_validator_singleton: MermaidValidator | None = None


def get_validator() -> MermaidValidator:
    """Process-wide validator instance (one Node child for all requests)."""
    global _validator_singleton  # noqa: PLW0603 - deliberate process singleton
    if _validator_singleton is None:
        _validator_singleton = MermaidValidator()
    return _validator_singleton


def _model_repair(kind: str, source: str, error: str, *, client, model: str) -> str:
    """Ask the model to rewrite the diagram given the exact parser error.

    The prompt carries the required header, syntax notes, and a known-valid
    skeleton for the kind — without these, small models echo the broken
    source back. Temperature is slightly above 0 to escape that attractor.
    """
    rules = KIND_RULES[kind]
    user = (
        f"This diagram is INVALID Mermaid 11 and was rejected by the parser.\n\n"
        f"PARSER ERROR:\n{error}\n\n"
        f"REQUIRED: the first line must be exactly '{rules['header']}'. {rules['notes']}\n\n"
        f"Example of VALID syntax for this diagram type:\n{rules['skeleton']}\n\n"
        f"INVALID SOURCE (rewrite it, preserving its meaning):\n{source}"
    )
    text = client.chat_structured(
        model=model,
        system=REPAIR_SYSTEM_PROMPT,
        user=user,
        schema=REPAIR_FORMAT,
        temperature=0.2,
        num_ctx=8192,
    )
    try:
        return str(json.loads(text)["mermaid"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return text


def repair_diagram(
    kind: str,
    source: str,
    *,
    validator: MermaidValidator,
    client=None,
    model: str | None = None,
    on_progress=None,
) -> tuple[str, dict[str, Any]]:
    """Run the full loop for one diagram; return (final_source, report)."""
    report: dict[str, Any] = {"kind": kind, "model_attempts": 0, "errors": []}

    src = normalize_frame(source)
    if not validator.available:
        final = sanitize(src, kind)
        report["status"] = "unvalidated"
        return final, report

    verdict = validator.check(src)
    if verdict["ok"]:
        report["status"] = "valid"
        return src, report
    report["errors"].append(verdict.get("error", ""))

    if client is not None and model:
        for attempt in range(1, MAX_MODEL_REPAIRS + 1):
            if on_progress is not None:
                on_progress({"diagram": kind, "state": "model-repair", "attempt": attempt})
            repaired = normalize_frame(
                _model_repair(kind, src, verdict.get("error", ""), client=client, model=model)
            )
            report["model_attempts"] = attempt
            verdict = validator.check(repaired)
            if verdict["ok"]:
                report["status"] = "repaired"
                return repaired, report
            report["errors"].append(verdict.get("error", ""))
            src = repaired

    # Sanitize the last repair output, and fall back to sanitizing the
    # ORIGINAL source — model repairs can mangle a dialect the structural
    # converters would have handled.
    for candidate in (src, normalize_frame(source)):
        sanitized = sanitize(candidate, kind)
        verdict = validator.check(sanitized)
        if verdict["ok"]:
            report["status"] = "sanitized"
            return sanitized, report
        report["errors"].append(verdict.get("error", ""))

    report["status"] = "stubbed"
    report["original_source"] = source
    report["needs_manual_review"] = True
    return STUBS[kind], report


def validate_and_repair_bundle(
    diagrams: dict[str, str],
    *,
    client=None,
    model: str | None = None,
    on_progress=None,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Repair all five diagrams; return (final diagrams, per-diagram reports)."""
    validator = get_validator()
    finals: dict[str, str] = {}
    reports: list[dict[str, Any]] = []
    for kind in DIAGRAM_KINDS:
        final, report = repair_diagram(
            kind,
            diagrams.get(kind, ""),
            validator=validator,
            client=client,
            model=model,
            on_progress=on_progress,
        )
        finals[kind] = final
        reports.append(report)
    return finals, reports
