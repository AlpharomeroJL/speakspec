# Speakspec 1.0.0

Local-first desktop app: speak your system, get a ship-grade AGENTS.md, architecture spec, ADRs, and Mermaid diagrams — all private, all on your machine.

## Highlights

- Self-contained Windows installer with bundled Python sidecar and Mermaid validator
- Settings screen: hardware override, model selection, fast pipeline, optional cloud Stage 3
- Sanitizer-first diagram repair for faster generation
- Session library with full-text search

## Install

1. Install [Ollama](https://ollama.com/download)
2. Run the Speakspec NSIS installer
3. First-run setup pulls a recommended model

## Privacy

Zero egress by default. Optional cloud Stage 3 sends architecture text only (never audio) when explicitly enabled with your API key.

## Verification

- Installer: `Speakspec_1.0.0_x64-setup.exe` (~115 MB, 120,464,705 bytes)
- Installer SHA-256: `3E6412494C6E88A1927A1098F14DD1CF9ACE99518324041E85C0633CE067FD79`
- Mermaid release gate: PASS (20 specs, 0 invalid)
- AGENTS.md gate: PASS (5/5; `gym-routes-webapp` passed on retry)
- Template gate: PASS
- ASR gate: PASS (GPU, 8.6x real-time on sample)
- Wireshark capture (no cloud): _(fill hash)_
- Wireshark capture (cloud enabled): _(fill hash)_

## Known limitations

- Windows 10/11 x64 only for v1.0.0
- **GPU ASR:** NVIDIA CUDA wheels are not bundled (installer size). CPU ASR works out of the box; GPU transcription requires installing `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` into the bundled sidecar venv.
- Default-tier full pipeline may take several minutes; enable **Fast pipeline** in Settings for shorter runs
