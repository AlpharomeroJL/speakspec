# Clean-VM release checklist (Windows 10 + Windows 11)

Run the full list on a fresh VM for each target OS before tagging a release.

## Environment

- [ ] Fresh Windows 10 x64 VM, fully updated, no dev tools installed
- [ ] Fresh Windows 11 x64 VM, fully updated, no dev tools installed
- [ ] Snapshot taken before install (so the run is repeatable)

## Install + first run

- [ ] Installer (<120 MB) installs without admin surprises; SHA-256 matches the published checksum
- [ ] App starts in under 3 seconds
- [ ] First-run hardware detection completes in under 5 seconds and reports
      the correct device (GPU name / CPU) — manual override works in settings
- [ ] Without Ollama installed: the app shows the specific "Ollama not
      installed" guidance with the install link — no crash
- [ ] With Ollama installed, no models: setup screen recommends the right tier
      for the VM's hardware; model download shows percent + ETA
- [ ] Interrupt the model download (kill Ollama mid-pull), restart: download
      resumes rather than restarting
- [ ] **Setup-friction gate:** first run with the small fallback model
      (Phi-4-mini / Gemma 4 4B class) completes record → AGENTS.md end-to-end
      in under 5 minutes total on the clean machine
- [ ] On a machine with Ollama + models pre-installed: complete session
      possible within 3 minutes of install

## Core loop

- [ ] Record 90 seconds; waveform moves in real time; pause/resume yields one
      continuous file; stop at silence works
- [ ] 10-minute recording transcribes within 2× real-time on RTX 4060+ (GPU)
      and completes without crash on CPU-only
- [ ] Transcript edits persist into the constraint screen output
- [ ] Constraint review shows stated/inferred labels; language info box when
      no language stated; inline edit changes Stage 2 output
- [ ] Interview answers visibly change the architecture (before/after diff)
- [ ] Pipeline (~90s recording): under 90s on RTX 4060+ with fast pipeline
      enabled or fast_fallback model, under 8 min CPU-only
- [ ] Pipeline (10-min recording): under 8 min on RTX 4060+ (default tier);
      under 90s only when fast pipeline is enabled and a fast_fallback model
      is installed
- [ ] All 5 diagrams render in-app; stubbed diagrams (if any) show the
      manual-review badge
- [ ] AGENTS.md under 200 lines with build/test/run commands present
- [ ] Exports: spec.md renders on GitHub; spec.docx opens in Word;
      spec.json parses; ADRs render on GitHub
- [ ] All five templates produce different output from one transcript
- [ ] Session library: persists across restart; search <500ms at 100 sessions;
      delete removes the directory; renders at 0 / 1 / 50+ sessions

## Privacy (release blocker)

- [ ] Wireshark capture per [privacy-verification.md](privacy-verification.md):
      zero non-localhost egress during a full session with no cloud key

## Cleanup behavior

- [ ] Quitting the app leaves no `python.exe`, `node.exe`, or `ollama` zombie
      processes attributable to Speakspec
- [ ] Uninstall removes the app; sessions dir is left (user data) and documented
