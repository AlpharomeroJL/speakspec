# Pipeline prompts

The canonical prompt text lives in [`docs/prompts/stage-prompts.md`](prompts/stage-prompts.md)
and is locked product IP — the sidecar parses that file at runtime
(`sidecar/speakspec/prompts.py`), so editing it changes behavior with no code
changes. This page explains each section.

## Shared mechanics (all stages)

- Requests go to the local Ollama `/api/chat` with `format` set to the stage's
  JSON schema from [`docs/schemas/`](schemas/) — generation is grammar-constrained,
  not parsed from free text.
- `temperature` 0 (Stage 3 may use 0.2 for prose), `num_ctx` always explicit and
  sized to the input (the 4096 default silently truncates transcripts).
- Output is validated by Pydantic (`sidecar/speakspec/schemas.py`). On failure
  the validation error is appended to the user message with an instruction to
  fix only the invalid fields; capped at 3 retries; then a structured error
  names the failing stage.

## Stage 1 — constraint extraction

Receives the raw transcript (+ interview answers on re-runs). Produces the
cleaned intent summary and the 11-category constraint set with stated/inferred
provenance. The two rules a senior reviewer should know:

- **Language is never inferred.** `language_preference` may only be `stated`;
  absent an explicit mention it is `"none stated"`. Enforced twice: by the
  prompt and by a semantic gate in the stage runner that rejects violating
  outputs.
- **Interview questions are 2–4, system-specific, never generic** — they target
  gaps that materially change the architecture.

## Stage 2 — architecture generation

Receives Stage 1 output (with user edits), interview answers, the template
preset, and the OSS knowledge base (including the language selection matrix).
Every decision must carry a confidence level and at least one ruled-out
alternative — the schema enforces the shape, the prompt enforces the attitude.
A semantic gate verifies an explicitly stated language preference was honored.

## Stage 3 — output generation

Receives the validated Stage 2 spec and emits the full artifact bundle in one
schema-constrained object. The prompt carries explicit warnings against the
known LLM Mermaid failure modes; the validate-and-repair loop
(`sidecar/speakspec/mermaid_repair.py`) and the AGENTS.md quality gate
(`sidecar/speakspec/agents_md.py`) then run on the result before anything is
shown or exported.
