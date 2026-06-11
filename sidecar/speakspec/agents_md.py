"""AGENTS.md quality gate and writer (release blocker, Phase 6).

Gates enforced on the hero artifact:

* hard cap: under 200 lines (pruning pass runs if exceeded, cutting prose
  and never commands),
* command-complete: at least one build, one test, and one run command —
  missing commands are reported so the UI can prompt the developer,
* no prose descriptions of files that already appear in the file tree,
* no restating rules a linter or compiler enforces.

``CLAUDE.md`` is ``@AGENTS.md`` plus overrides only if genuinely present.
"""

import re
from pathlib import Path
from typing import Any

MAX_LINES = 200

# Substrings that identify build/test/run commands across common stacks.
_COMMAND_PATTERNS: dict[str, tuple[str, ...]] = {
    "build": (
        "build",
        "compile",
        "pip install",
        "npm install",
        "pnpm install",
        "cargo check",
    ),
    "test": ("test", "pytest", "jest", "vitest", "go vet"),
    "run": ("run", "start", "serve", "dev", "uvicorn", "node ", "python -m", "watch"),
}

# Lines that merely restate what a linter/compiler already enforces.
_LINTER_NOISE = (
    "unused import",
    "unused variable",
    "trailing whitespace",
    "line length",
    "lines under",
    "characters per line",
    "must be formatted",
    "run the formatter",
    "no console.log",
    "type annotations are required",
    "strict null checks",
    "missing semicolons",
)


def _is_command_line(line: str) -> bool:
    """Whether a line carries an executable command (backticked or labeled)."""
    return (
        "`" in line
        or re.match(r"^\s*[-*]?\s*(build|test|lint|run|deploy|start)\s*:", line, re.I) is not None
    )


def detect_commands(agents_md: str) -> dict[str, list[str]]:
    """Find build/test/run commands present in the document."""
    found: dict[str, list[str]] = {"build": [], "test": [], "run": []}
    for line in agents_md.splitlines():
        if not _is_command_line(line):
            continue
        lowered = line.lower()
        for kind, patterns in _COMMAND_PATTERNS.items():
            if any(p in lowered for p in patterns):
                found[kind].append(line.strip())
    return found


def _tree_filenames(file_tree: str) -> set[str]:
    """Extract file names (with extensions) from a monospace tree."""
    names: set[str] = set()
    for line in file_tree.splitlines():
        cleaned = line.split("#")[0]
        cleaned = re.sub(r"[│├└─|`\\-]+", " ", cleaned)
        for token in cleaned.split():
            if "." in token.strip("/") and not token.startswith("."):
                names.add(token.strip("/").split("/")[-1])
    return names


def find_violations(agents_md: str, file_tree: str) -> list[dict[str, str]]:
    """Lines that describe tree files in prose, or restate linter rules."""
    violations: list[dict[str, str]] = []
    tree_names = _tree_filenames(file_tree)
    for idx, line in enumerate(agents_md.splitlines(), start=1):
        lowered = line.lower()
        if any(noise in lowered for noise in _LINTER_NOISE):
            violations.append(
                {"line": str(idx), "kind": "linter-duplication", "text": line.strip()}
            )
            continue
        if _is_command_line(line):
            continue
        mentioned = [n for n in tree_names if n.lower() in lowered]
        # Prose = long sentence about a file; pointers ("start at x.py") stay.
        if mentioned and len(line.split()) > 14:
            violations.append({"line": str(idx), "kind": "file-tree-prose", "text": line.strip()})
    return violations


def _collapse_blank_runs(lines: list[str]) -> list[str]:
    """At most one consecutive blank line."""
    out: list[str] = []
    for line in lines:
        if line.strip() == "" and out and out[-1].strip() == "":
            continue
        out.append(line)
    return out


def prune(agents_md: str, file_tree: str) -> str:
    """Reduce the document below the cap: prose first, commands never."""
    lines = agents_md.splitlines()
    violation_idx = {int(v["line"]) for v in find_violations(agents_md, file_tree)}
    lines = [ln for i, ln in enumerate(lines, start=1) if i not in violation_idx]
    lines = _collapse_blank_runs(lines)

    if len(lines) > MAX_LINES:
        # Trim list-heavy tail sections, keeping commands and constraints.
        lines = _trim_section(lines, "open questions", keep=5)
        lines = _trim_section(lines, "first tasks", keep=10)
    if len(lines) > MAX_LINES:
        # Last resort: drop non-command prose lines from the bottom up.
        kept: list[str] = []
        overflow = len(lines) - (MAX_LINES - 1)  # land strictly under the cap
        for line in reversed(lines):
            if (
                overflow > 0
                and line.strip()
                and not _is_command_line(line)
                and not line.startswith("#")
            ):
                overflow -= 1
                continue
            kept.append(line)
        lines = list(reversed(kept))
    return "\n".join(_collapse_blank_runs(lines)).strip() + "\n"


def _trim_section(lines: list[str], header_contains: str, keep: int) -> list[str]:
    """Cap the number of list items in the section whose header matches."""
    out: list[str] = []
    in_section = False
    items = 0
    for line in lines:
        if line.lstrip().startswith("#"):
            in_section = header_contains in line.lower()
            items = 0
        if in_section and re.match(r"\s*([-*]|\d+\.)\s", line):
            items += 1
            if items > keep:
                continue
        out.append(line)
    return out


def normalize_shim(shim: str) -> str:
    """Collapse whitespace-only variations of the shim to the canonical form."""
    stripped = shim.strip()
    if stripped == "@AGENTS.md" or not stripped:
        return "@AGENTS.md\n"
    return shim if shim.endswith("\n") else shim + "\n"


def gate_report(agents_md: str, file_tree: str) -> dict[str, Any]:
    """Evaluate every gate; non-mutating."""
    lines = agents_md.count("\n") + (0 if agents_md.endswith("\n") else 1)
    commands = detect_commands(agents_md)
    missing = [k for k, v in commands.items() if not v]
    violations = find_violations(agents_md, file_tree)
    return {
        "lines": lines,
        "under_cap": lines < MAX_LINES,
        "commands": commands,
        "missing_commands": missing,
        "command_complete": not missing,
        "violations": violations,
        "passes": lines < MAX_LINES and not missing and not violations,
    }


def apply_gate(agents_md: str, file_tree: str) -> tuple[str, dict[str, Any]]:
    """Run the gate; prune and re-check if anything fails.

    Returns the final text and the report (with ``pruned`` flag and the
    pre-prune line/violation counts attached).
    """
    report = gate_report(agents_md, file_tree)
    if report["passes"]:
        report["pruned"] = False
        return agents_md, report
    pruned_text = prune(agents_md, file_tree)
    final_report = gate_report(pruned_text, file_tree)
    final_report["pruned"] = True
    final_report["before"] = {"lines": report["lines"], "violations": len(report["violations"])}
    return pruned_text, final_report


def write_agent_files(
    agents_md: str, claude_md_shim: str, file_tree: str, dest_dir: Path
) -> dict[str, Any]:
    """Gate, then write AGENTS.md + CLAUDE.md into ``dest_dir``."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    final_md, report = apply_gate(agents_md, file_tree)
    (dest_dir / "AGENTS.md").write_text(final_md, encoding="utf-8", newline="\n")
    (dest_dir / "CLAUDE.md").write_text(
        normalize_shim(claude_md_shim), encoding="utf-8", newline="\n"
    )
    report["written"] = [str(dest_dir / "AGENTS.md"), str(dest_dir / "CLAUDE.md")]
    return report
