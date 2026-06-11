# Contributing to Speakspec

Thanks for considering it. The highest-leverage contributions need **zero code**:
templates, the OSS knowledge base, and the tech-vocab dictionary are plain JSON.

## Dev setup

Prerequisites: Rust stable (+ clippy, rustfmt), Node LTS + pnpm, Python 3.11+,
Ollama running locally, and Node for the Mermaid validator.

```bash
git clone https://github.com/joseflong/speakspec && cd speakspec
pnpm install
python -m venv sidecar/.venv
sidecar/.venv/Scripts/python -m pip install -r sidecar/requirements-dev.txt
sidecar/.venv/Scripts/python -m pip install -e sidecar --no-deps
cd tools/mermaid-validate && pnpm install && cd ../..
pnpm tauri dev
```

## Running checks

| What | Command |
|---|---|
| Rust lint | `cd src-tauri && cargo clippy --all-targets` |
| Rust tests | `cd src-tauri && cargo test` |
| Python lint | `sidecar/.venv/Scripts/ruff check sidecar` |
| Python tests | `cd sidecar && .venv/Scripts/python -m pytest` |
| Frontend types | `pnpm exec tsc --noEmit` |
| Mermaid release gate | `cd sidecar && .venv/Scripts/python tests/run_mermaid_corpus.py` |
| AGENTS.md release gate | `cd sidecar && .venv/Scripts/python tests/run_agents_gate.py` |

House rules (enforced in CI): no `unwrap()`/`expect()` outside tests, no Clippy
warnings, ruff clean, every public Rust fn documented, every Python function
docstringed, `num_ctx` explicit on every Ollama request, no hardcoded paths or
model names, and zero network egress by default.

## Adding a prompt template

1. Copy an entry in [`templates/presets.json`](templates/presets.json).
2. Give it a unique `name`, an honest `optimize_for`, and (optionally) a
   `default_language_tendency`.
3. Run the app — new templates appear in the constraint review screen with no
   code changes. Invalid JSON shows a clear error instead of crashing.

## Adding to the OSS knowledge base

[`templates/oss-knowledge-base.json`](templates/oss-knowledge-base.json) feeds
Stage 2 so it recommends mature libraries instead of custom builds. Add entries
under the right domain with `name`, `language`, a known-good minimum `version`,
and a one-line `use_for`. Recommendations must be current — superseded or
deprecated libraries are removed, not kept for nostalgia.

## Adding tech-vocab corrections

[`dicts/tech-vocab.json`](dicts/tech-vocab.json) fixes ASR mishearings
("fast api" → "FastAPI"). Keys must be phrases that essentially never occur in
ordinary English — the clean-text corpus test (`tests/test_vocab.py`) fails any
entry that alters normal prose.

## PR process

1. Fork, branch from `main`, keep PRs focused.
2. Run the checks table above; all must pass.
3. The three release blockers (Mermaid corpus zero-invalid, AGENTS.md gate,
   privacy/no-egress) are non-negotiable — a PR that regresses one will not
   merge regardless of how nice the feature is.
4. Conventional commit messages, please (`feat:`, `fix:`, `docs:` …).
