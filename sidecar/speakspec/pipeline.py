"""The three-stage Speakspec pipeline (Contract C consumer).

Each stage: render the locked prompts, call Ollama with the stage schema as
``format``, explicit ``temperature`` and ``num_ctx``, stream tokens up, then
validate with Pydantic plus stage-specific semantic rules. On validation
failure the model gets the error appended and must fix only the invalid
fields; capped at 3 retries, then a structured error names the failing stage.
"""

import json
import logging
from typing import Any

from pydantic import BaseModel, ValidationError

from speakspec import prompts
from speakspec.cloud_client import CloudClient
from speakspec.config import get_config, templates_dir
from speakspec.messages import SidecarError
from speakspec.model_select import choose_model, resolve_repair_model, resolve_stage_model
from speakspec.ollama_client import OllamaClient
from speakspec.rpc import RequestContext
from speakspec.schemas import STAGE_MODELS, ConstraintExtraction, OutputBundle, load_stage_schema

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
# Output budget added to the input estimate when sizing num_ctx, and used as
# the explicit num_predict generation cap. Stage 1 gets generous room because
# fact-dense transcripts legitimately produce long constraint sets; Stage 3
# emits every artifact in one object and needs the most.
_OUTPUT_BUDGET = {1: 6144, 2: 6144, 3: 8192}
# Rough chars-per-token for mixed English/JSON; deliberately conservative.
_CHARS_PER_TOKEN = 3.0


def size_num_ctx(stage: int, system: str, user: str) -> int:
    """Explicit context size: input estimate + output budget, clamped.

    Never relies on the Ollama 4096 default, which silently truncates
    transcripts.
    """
    config = get_config()
    input_tokens = int(len(system + user) / _CHARS_PER_TOKEN)
    needed = input_tokens + _OUTPUT_BUDGET[stage]
    rounded = ((needed + 1023) // 1024) * 1024
    return max(config["num_ctx_min"], min(rounded, config["num_ctx_max"]))


def stated_language(constraints: list[dict[str, Any]] | None) -> str | None:
    """Return the explicitly stated language preference, if any."""
    for constraint in constraints or []:
        if constraint.get("category") != "language_preference":
            continue
        value = str(constraint.get("value", "")).strip()
        if value and value.lower() not in ("none stated", "none", "null", "n/a"):
            return value
    return None


def semantic_check(stage: int, parsed: BaseModel, context: dict[str, Any] | None = None) -> None:
    """Stage rules the JSON schema cannot express. Raises ``ValueError``."""
    if stage == 1 and isinstance(parsed, ConstraintExtraction):
        for constraint in parsed.constraints:
            if constraint.category == "language_preference" and constraint.source == "inferred":
                raise ValueError(
                    "constraints: language_preference may never have source='inferred'. "
                    "If the speaker did not explicitly name a language, set value to "
                    "'none stated' and source to 'stated'."
                )
    if stage == 2 and context is not None:
        preferred = stated_language(context.get("constraints"))
        if preferred:
            recommended = parsed.recommended_language.language  # type: ignore[attr-defined]
            a, b = preferred.lower(), recommended.lower()
            if a not in b and b not in a:
                raise ValueError(
                    f"recommended_language: the user explicitly stated '{preferred}', "
                    f"which must be honored (you chose '{recommended}'). Set the "
                    "language to the stated preference, set overridden_by_user "
                    "appropriately, and flag any tradeoffs in the rationale."
                )


def run_stage(
    stage: int,
    user_message: str,
    *,
    client: OllamaClient,
    model: str,
    ctx: RequestContext | None = None,
    context: dict[str, Any] | None = None,
) -> BaseModel:
    """Run one pipeline stage and return its validated output model.

    ``context`` carries cross-stage facts for semantic checks (e.g. the
    Stage 1 constraints when validating Stage 2's language recommendation).
    """
    schema = load_stage_schema(stage)
    system = prompts.system_prompt(stage)
    model_cls = STAGE_MODELS[stage]
    temperature = 0.2 if stage == 3 else 0.0
    num_ctx = size_num_ctx(stage, system, user_message)

    on_token = ctx.emit_token if ctx is not None else None
    cancelled = ctx.check_cancelled if ctx is not None else None
    if ctx is not None:
        ctx.emit_progress(
            {"stage": stage, "state": "calling-model", "model": model, "num_ctx": num_ctx}
        )

    message = user_message
    last_error = "unknown"
    for attempt in range(1 + MAX_RETRIES):
        if cancelled is not None and cancelled():
            raise SidecarError("cancelled", "The pipeline was cancelled.")
        text = client.chat_structured(
            model=model,
            system=system,
            user=message,
            schema=schema,
            temperature=temperature,
            num_ctx=num_ctx,
            num_predict=_OUTPUT_BUDGET[stage],
            on_token=on_token,
            cancelled=cancelled,
        )
        try:
            parsed = model_cls.model_validate(json.loads(text))
            semantic_check(stage, parsed, context)
            return parsed
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = str(exc)
            logger.warning("stage %d attempt %d failed validation: %s", stage, attempt + 1, exc)
            if ctx is not None:
                ctx.emit_progress({"stage": stage, "state": "retrying", "attempt": attempt + 1})
            # Truncated JSON means the generation hit the length cap: the
            # retry must also demand brevity or it will truncate again.
            length_note = (
                "\nYour output was cut off because it exceeded the length limit. "
                "Be concise: at most 2 entries per constraint category, short "
                "strings, no repetition."
                if isinstance(exc, json.JSONDecodeError)
                else ""
            )
            message = (
                f"{user_message}\n\n"
                f"YOUR PREVIOUS OUTPUT FAILED VALIDATION WITH THIS ERROR:\n{last_error}\n"
                f"Fix only the invalid fields and re-emit the complete JSON object.{length_note}"
            )

    raise SidecarError(
        "stage-validation-failed",
        f"Stage {stage} output failed validation after {MAX_RETRIES} retries. "
        f"Last error: {last_error[:500]}",
        {"stage": stage},
    )


def run_stage_cloud(
    stage: int,
    user_message: str,
    *,
    cloud: CloudClient,
    model: str,
    ctx: RequestContext | None = None,
    context: dict[str, Any] | None = None,
) -> BaseModel:
    """Run Stage 3 via a cloud provider instead of local Ollama."""
    schema = load_stage_schema(stage)
    system = prompts.system_prompt(stage)
    model_cls = STAGE_MODELS[stage]
    temperature = 0.2

    on_token = ctx.emit_token if ctx is not None else None
    cancelled = ctx.check_cancelled if ctx is not None else None
    if ctx is not None:
        ctx.emit_progress({"stage": stage, "state": "calling-cloud", "model": model})

    message = user_message
    last_error = "unknown"
    for attempt in range(1 + MAX_RETRIES):
        if cancelled is not None and cancelled():
            raise SidecarError("cancelled", "The pipeline was cancelled.")
        text = cloud.chat_structured(
            model=model,
            system=system,
            user=message,
            schema=schema,
            temperature=temperature,
            on_token=on_token,
            cancelled=cancelled,
        )
        try:
            parsed = model_cls.model_validate(json.loads(text))
            semantic_check(stage, parsed, context)
            return parsed
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = str(exc)
            logger.warning("cloud stage %d attempt %d failed: %s", stage, attempt + 1, exc)
            if ctx is not None:
                ctx.emit_progress({"stage": stage, "state": "retrying", "attempt": attempt + 1})
            message = (
                f"{user_message}\n\n"
                f"YOUR PREVIOUS OUTPUT FAILED VALIDATION WITH THIS ERROR:\n{last_error}\n"
                f"Fix only the invalid fields and re-emit the complete JSON object."
            )

    raise SidecarError(
        "stage-validation-failed",
        f"Cloud stage {stage} failed validation after {MAX_RETRIES} retries.",
        {"stage": stage},
    )


def load_preset(template_name: str) -> dict[str, str]:
    """Look up a template preset by name from ``templates/presets.json``."""
    path = templates_dir() / "presets.json"
    with path.open(encoding="utf-8") as fh:
        presets = {p["name"]: p for p in json.load(fh)["presets"]}
    if template_name not in presets:
        raise SidecarError(
            "unknown-template",
            f"Unknown template preset '{template_name}'.",
            {"known": sorted(presets)},
        )
    return presets[template_name]


def load_oss_knowledge_base() -> dict:
    """Load the curated OSS knowledge base injected into Stage 2."""
    path = templates_dir() / "oss-knowledge-base.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def resolve_model(explicit: str | None, client: OllamaClient) -> str:
    """Pick the model: explicit request > config default > best installed."""
    config = get_config()
    installed = client.list_models()
    return choose_model(installed, preferred=explicit or config["default_model"])


def make_client() -> OllamaClient:
    """Construct the Ollama client from configuration."""
    return OllamaClient(get_config()["ollama_url"])


def stage1_message(raw_transcript: str, interview_answers: str) -> str:
    """Render the Stage 1 user message from the locked template."""
    return prompts.user_message(
        1, raw_transcript=raw_transcript, interview_answers=interview_answers or "(none)"
    )


def stage2_message(constraints_json: str, interview_answers: str, template_name: str) -> str:
    """Render the Stage 2 user message from the locked template."""
    preset = load_preset(template_name)
    return prompts.user_message(
        2,
        constraints_json=constraints_json,
        interview_answers=interview_answers or "(none)",
        template_name=preset["name"],
        template_optimize_for=preset["optimize_for"],
        oss_knowledge_base_json=json.dumps(load_oss_knowledge_base(), indent=0),
    )


def stage3_message(architecture_spec_json: str) -> str:
    """Render the Stage 3 user message from the locked template."""
    return prompts.user_message(3, architecture_spec_json=architecture_spec_json)


# ---------------------------------------------------------------------------
# AGENTS.md micro-regeneration
# ---------------------------------------------------------------------------

# Small models reliably write '@AGENTS.md' (the shim) or a stub into the
# agents_md field of the big Stage 3 bundle, and whole-stage retries cannot
# coax them out of it. A focused single-artifact call fixes what the bundle
# call cannot — same architecture as the Mermaid repair loop.

AGENTS_MD_FORMAT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["agents_md"],
    "properties": {"agents_md": {"type": "string"}},
}

AGENTS_MD_SYSTEM_PROMPT = (
    "You write AGENTS.md files: the agent context file AI coding tools read "
    "first. Produce only the markdown document. Non-negotiable rules: under "
    "200 lines; lean and command-first; fixed section order: (1) one-line "
    "project description, (2) tech stack with exact versions, (3) exact "
    "commands - build, test, lint, run, deploy - each in backticks, "
    "(4) 3-5 key directories, one line each, pointing at files, (5) hard "
    "constraints that must always be true, (6) a do-not block of what must "
    "never happen, (7) first tasks in build order, (8) open questions. Do not "
    "describe files that appear in the provided file tree; do not restate "
    "anything a linter or compiler enforces; do not pad."
)


def agents_md_is_real(doc: str) -> bool:
    """Structural floor: a real document, not the shim or a stub.

    Deliberately minimal — multi-line with at least one backticked command.
    Section structure and command completeness are the full quality gate's
    job (``agents_md.py``); this only catches shim/stub substitution.
    """
    text = doc.strip()
    return text != "@AGENTS.md" and text.count("\n") >= 9 and "`" in text


def ensure_real_agents_md(
    bundle: OutputBundle,
    spec_json: str,
    *,
    client: OllamaClient,
    model: str,
    ctx: RequestContext | None = None,
) -> OutputBundle:
    """Replace a fake ``agents_md`` via a focused regeneration call.

    Two attempts; raises ``SidecarError`` if the model still cannot produce
    a structurally real document.
    """
    if agents_md_is_real(bundle.agents_md):
        return bundle
    user = (
        f"ARCHITECTURE SPEC:\n{spec_json}\n\n"
        f"FILE TREE (do not re-describe these files):\n{bundle.file_tree}\n\n"
        "Write the complete AGENTS.md now."
    )
    system = AGENTS_MD_SYSTEM_PROMPT
    for attempt in range(2):
        if ctx is not None:
            ctx.emit_progress(
                {"stage": 3, "state": "regenerating-agents-md", "attempt": attempt + 1}
            )
        text = client.chat_structured(
            model=model,
            system=system,
            user=user,
            schema=AGENTS_MD_FORMAT,
            temperature=0.2,
            num_ctx=size_num_ctx(3, system, user),
            num_predict=4096,
        )
        try:
            doc = str(json.loads(text)["agents_md"])
        except (json.JSONDecodeError, KeyError, TypeError):
            doc = text
        if agents_md_is_real(doc):
            return bundle.model_copy(update={"agents_md": doc})
        user += (
            "\n\nYOUR PREVIOUS ATTEMPT WAS NOT A REAL DOCUMENT. Write the full "
            "multi-section markdown file with backticked commands."
        )
    raise SidecarError(
        "agents-md-generation-failed",
        "The model could not produce a structurally complete AGENTS.md after "
        "focused retries. Try a larger model tier.",
        {"stage": 3},
    )


# ---------------------------------------------------------------------------
# RPC handlers (registered in handlers/__init__.py)
# ---------------------------------------------------------------------------


def handle_models_list(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """List installed Ollama models and the auto-selected default."""
    client = make_client()
    installed = client.list_models()
    selected = None
    if installed:
        selected = choose_model(installed, preferred=get_config()["default_model"])
    return {
        "models": [{"name": m["name"], "size": m.get("size", 0)} for m in installed],
        "selected": selected,
    }


def handle_stage1(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """Run Stage 1 on a raw transcript (+ optional interview answers)."""
    transcript = params.get("transcript", "")
    if not transcript.strip():
        raise SidecarError("empty-transcript", "There is no transcript text to analyze.")
    client = make_client()
    model = resolve_stage_model(1, params.get("model"), client)
    result = run_stage(
        1,
        stage1_message(transcript, params.get("interview_answers", "")),
        client=client,
        model=model,
        ctx=ctx,
    )
    return {"model": model, "result": result.model_dump()}


def handle_stage2(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """Run Stage 2 on (possibly user-edited) Stage 1 output."""
    constraints = params.get("constraints")
    if not constraints:
        raise SidecarError("missing-constraints", "Stage 2 needs the Stage 1 constraint output.")
    client = make_client()
    model = resolve_model(params.get("model"), client)
    result = run_stage(
        2,
        stage2_message(
            json.dumps(constraints, indent=1),
            params.get("interview_answers", ""),
            params.get("template", "Solo MVP"),
        ),
        client=client,
        model=model,
        ctx=ctx,
        context=constraints if isinstance(constraints, dict) else None,
    )
    return {"model": model, "result": result.model_dump()}


def handle_stage3(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """Run Stage 3, then the Mermaid validate-and-repair loop (Phase 5)."""
    from speakspec.mermaid_repair import validate_and_repair_bundle

    spec = params.get("architecture_spec")
    if not spec:
        raise SidecarError("missing-spec", "Stage 3 needs the Stage 2 architecture spec.")
    client = make_client()
    spec_json = json.dumps(spec, indent=1)
    cloud = CloudClient.from_config()
    if cloud is not None:
        cloud_model = params.get("cloud_model") or "gpt-4o-mini"
        result = run_stage_cloud(
            3,
            stage3_message(spec_json),
            cloud=cloud,
            model=cloud_model,
            ctx=ctx,
        )
        model = f"cloud:{cloud_model}"
        repair_model = resolve_repair_model(client)
        agents_model = repair_model
    else:
        model = resolve_stage_model(3, params.get("model"), client)
        result = run_stage(
            3,
            stage3_message(spec_json),
            client=client,
            model=model,
            ctx=ctx,
        )
        repair_model = resolve_repair_model(client)
        agents_model = repair_model
    result = ensure_real_agents_md(
        result, spec_json, client=client, model=agents_model, ctx=ctx
    )
    ctx.emit_progress({"stage": 3, "state": "validating-diagrams"})
    finals, reports = validate_and_repair_bundle(
        result.diagrams.model_dump(),
        client=client,
        model=repair_model,
        on_progress=lambda d: ctx.emit_progress({"stage": 3, **d}),
    )
    bundle = result.model_dump()
    bundle["diagrams"] = finals
    return {"model": model, "result": bundle, "diagram_reports": reports}
