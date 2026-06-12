# Speakspec v1.0.0 release checklist

Run this after `pnpm tauri build` produces an installer artifact.

## Build artifacts

- [ ] `pnpm tauri build` completes; NSIS installer under `src-tauri/target/release/bundle/`
- [ ] Installer SHA-256 recorded in release notes
- [ ] Installer size under 120 MB (or documented exception)

## Automated gates

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run-release-gates.ps1
```

## Marketing assets

- [ ] `docs/assets/hero.png` — product hero image
- [ ] `docs/assets/demo.gif` — full speak → generate → paste loop (record with ScreenToGif or similar)

## Live paste tests

Using outputs from `sidecar/tests/out/agents_gate/`:

- [ ] Claude Code: paste AGENTS.md for 3 project types; agent scaffolds without confusion
- [ ] Cursor: paste AGENTS.md for 1 project type

## Diagram rendering

Export a sample `spec.md` and verify all 5 diagrams render in:

- [ ] GitHub markdown (light theme)
- [ ] GitHub markdown (dark theme)
- [ ] Obsidian

## Privacy (Wireshark)

Per [privacy-verification.md](privacy-verification.md):

- [ ] Capture with no cloud key — zero non-localhost egress during full session
- [ ] Capture with cloud Stage 3 enabled — egress only to configured provider
- [ ] Archive capture file SHA-256 hashes in release notes

## Clean-VM installs

Per [clean-vm-checklist.md](clean-vm-checklist.md):

- [ ] Windows 10 x64 fresh VM
- [ ] Windows 11 x64 fresh VM

## Publish

```powershell
gh release create v1.0.0 path/to/Speakspec_1.0.0_x64-setup.exe --title "Speakspec 1.0.0" --notes-file RELEASE_NOTES.md
```
