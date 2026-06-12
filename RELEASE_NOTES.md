# Speakspec 1.0.1

Patch release: bundles NVIDIA CUDA wheels so GPU transcription works out of the box on NVIDIA hardware.

## What's new

- Installer now includes `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` for bundled GPU ASR
- Optional cuDNN engine DLLs pruned to keep the NSIS build under its 2 GB limit
- CPU ASR remains the fallback when no CUDA GPU is available

## Install

1. Install [Ollama](https://ollama.com/download)
2. Run the Speakspec NSIS installer (~780 MB)
3. First-run setup pulls a recommended model

## Privacy

Zero egress by default. Optional cloud Stage 3 sends architecture text only (never audio) when explicitly enabled with your API key.

## Verification

- Installer: `Speakspec_1.0.1_x64-setup.exe` (~780 MB, 817,898,266 bytes)
- Installer SHA-256: `AC869C2EFA44CD4243C4FDF1E33C528BF0EBC05E7103E2F3BC85FED5BFB949A2`
- ASR gate: PASS (GPU, ~8.7x real-time on sample with bundled wheels)

## Known limitations

- Windows 10/11 x64 only
- Installer is ~780 MB (up from ~115 MB in v1.0.0) due to CUDA runtime DLLs
- Default-tier full pipeline may take several minutes; enable **Fast pipeline** in Settings for shorter runs
