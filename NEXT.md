# NEXT — precise resume point and honest gap list

Updated: 2026-06-11 (end of the one-shot build session)

All 11 build phases were executed and verified in order; every per-phase gate
that can run on this machine ran for real (results in the final session
report and commit messages). What follows is the truthful map of what is
real, what is partial, and what must happen before tagging v1.0.

## Remaining work, in priority order

### 1. Bundle the Python sidecar into the installer (the one real engineering gap)
The NSIS installer (3.9 MB) ships the app but **not the sidecar venv**.
Today a release build finds the sidecar via the dev layout or
`SPEAKSPEC_SIDECAR_PYTHON`/`SPEAKSPEC_SIDECAR_DIR` env vars
(resolution logic + friendly error already implemented in
`src-tauri/src/sidecar/mod.rs`).
Plan: first-run bootstrap (download python-embeddable + `pip install
sidecar/` into `%APPDATA%`) keeps the installer tiny and mirrors the
models-at-runtime philosophy; alternatively bundle a prebuilt venv as a
Tauri resource (~100 MB, still under the 120 MB cap). Either fits the
existing path resolution; pick one and wire `docs/clean-vm-checklist.md`.
Note: GPU ASR needs the `nvidia-cublas-cu12`/`nvidia-cudnn-cu12` wheels
(venv-local; DLL-dir registration already in `asr.py`).

### 2. Manual release-blocker items (documented, not yet performed)
- Demo GIF (`docs/assets/demo.gif`) — full loop incl. paste into Claude Code.
- Hero image (`docs/assets/hero.png`).
- Wireshark zero-egress capture per `docs/privacy-verification.md`.
- AGENTS.md live paste-tests: Claude Code on 3 project types, Cursor on 1
  (generated samples are in `sidecar/tests/out/agents_gate/` after running
  `tests/run_agents_gate.py`).
- GitHub (light+dark) + Obsidian rendering pass for the 5 diagrams.
- Clean-VM install runs (Win10 + Win11) per `docs/clean-vm-checklist.md`.

### 3. Performance target not met with the default-class model
DOD wants the full pipeline under 90 s on RTX 4060+. Measured with
qwen3:8b including validation retries and diagram repairs: ~4–6 min.
Single stages: S1 15–60 s, S2 ~90 s, S3 ~80 s, plus repair/micro-repair
calls. Options: fast_fallback tier for S1/S3, fewer repair rounds via
sanitizer-first ordering, or accepting the target only for the
power-user tier. Decide before release; the checklist box stays unchecked.

### 4. Smaller, known gaps
- **Settings UI**: everything is config/env-driven (`config/models.json`,
  `SPEAKSPEC_*` vars) but there is no settings screen; DOD wants manual
  hardware override in settings.
- **Cloud Stage 3** (optional per PRD): not implemented; no key entry UI.
  Privacy default (zero egress) is therefore trivially true.
- **Interview auto-mode toggle**: skipping = leave answers blank (works);
  a dedicated toggle is not built.
- **CI**: no remote/CI configured; gates run locally
  (`CONTRIBUTING.md` has the command table).
- **mermaid bundle size**: lazy-load the mermaid import in `Results.tsx`
  to silence the >500 kB chunk warning.
- **Recording-session reuse**: `start_recording` creates the session dir;
  the recorder UI ignores the returned `session_dir` until stop (cosmetic).

### 5. Model-quality notes (qwen3:8b, default tier)
- Stage 1 sometimes files scale/timeline facts under `deployment_target`
  (schema-valid; category quality improves with the 12B+/27B tiers).
- `agents_md` inside the Stage 3 bundle is reliably the shim string; the
  focused micro-regeneration (`ensure_real_agents_md`) fixes it — keep it.
- Diagrams: zero invalid across the 20-spec corpus; expect `repaired`/
  `sanitized` provenance, occasionally a stub on pathological output.

## Resume command crib
- All gates: see the table in `CONTRIBUTING.md`.
- Mermaid release gate: `sidecar/.venv/Scripts/python tests/run_mermaid_corpus.py`
- AGENTS.md gate: `... tests/run_agents_gate.py`
- ASR gate: `... tests/gen_tts_sample.ps1` then `... tests/run_asr_check.py`
- Templates gate: `... tests/run_template_check.py`
