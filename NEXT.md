# NEXT — v1.0.0 shipped

Updated: 2026-06-11

Speakspec v1.0.0 engineering is complete. Remaining items are **manual release
verification** — run [docs/RELEASE.md](docs/RELEASE.md) before tagging.

## What shipped in v1.0.0

- Bundled Python sidecar + Node Mermaid validator in the NSIS installer
  (`scripts/package-runtime.ps1`, `src-tauri/resources/speakspec-runtime/`)
- Settings UI: hardware override, model picker, interview auto-mode, cloud
  Stage 3, fast pipeline toggle
- Cloud Stage 3 (optional, off by default) via OpenAI/Anthropic APIs
- Performance: sanitizer-first diagram repair, parallel validation, fast repair
  model routing, per-stage model selection
- CI: `.github/workflows/ci.yml`
- Polish: lazy-loaded Mermaid in Results, recorder session_dir fix

## Manual release checklist (you run these)

See [docs/RELEASE.md](docs/RELEASE.md):

1. Record `docs/assets/demo.gif`
2. Wireshark captures (no cloud + cloud enabled)
3. AGENTS.md live paste tests (Claude Code ×3, Cursor ×1)
4. Diagram rendering (GitHub light/dark, Obsidian)
5. Clean-VM installs (Win10 + Win11)
6. `gh release create v1.0.0`

## Gate commands

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run-release-gates.ps1
# Requires Ollama running for mermaid/AGENTS/template gates
```

Or individually — table in [CONTRIBUTING.md](CONTRIBUTING.md).
