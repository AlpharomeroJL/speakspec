"""Contract D: faster-whisper transcription with hardware detection.

GPU (CUDA) -> ``large-v3-turbo`` float16; CPU -> ``small.en`` int8. Both
overridable via config/env. Streams per-segment progress, applies the
technical-vocabulary correction pass, and falls back to CPU with a notice on
GPU out-of-memory instead of crashing (DOD 1.3).
"""

import logging
import os
from pathlib import Path
from typing import Any

from speakspec import vocab
from speakspec.messages import SidecarError
from speakspec.rpc import RequestContext

logger = logging.getLogger(__name__)

GPU_MODEL = os.environ.get("SPEAKSPEC_ASR_GPU_MODEL", "large-v3-turbo")
CPU_MODEL = os.environ.get("SPEAKSPEC_ASR_CPU_MODEL", "small.en")

_model_cache: dict[tuple[str, str], Any] = {}


def detect_hardware() -> dict[str, Any]:
    """Pick the ASR device/model from the machine's capabilities."""
    try:
        import ctranslate2

        cuda_devices = ctranslate2.get_cuda_device_count()
    except Exception:  # noqa: BLE001 - any probe failure means CPU path
        cuda_devices = 0
    if cuda_devices > 0:
        return {
            "device": "cuda",
            "model": GPU_MODEL,
            "compute_type": "float16",
            "cuda_devices": cuda_devices,
        }
    return {"device": "cpu", "model": CPU_MODEL, "compute_type": "int8", "cuda_devices": 0}


def _register_cuda_dll_dirs() -> None:
    """Make pip-installed NVIDIA runtime DLLs loadable on Windows.

    ctranslate2's GPU path needs cuBLAS/cuDNN. The supported zero-system-
    install route is the ``nvidia-cublas-cu12``/``nvidia-cudnn-cu12`` wheels;
    their ``bin`` dirs must be registered with the DLL loader explicitly.
    """
    if os.name != "nt":
        return
    import site

    for base in site.getsitepackages():
        nvidia_dir = Path(base) / "nvidia"
        if not nvidia_dir.is_dir():
            continue
        for bin_dir in nvidia_dir.glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
                os.environ["PATH"] = f"{bin_dir};{os.environ.get('PATH', '')}"
            except OSError:  # pragma: no cover - defensive
                continue


def _load_model(model_size: str, device: str, compute_type: str):
    """Load (and cache) a faster-whisper model."""
    key = (model_size, device)
    if key not in _model_cache:
        from faster_whisper import WhisperModel

        if device == "cuda":
            _register_cuda_dll_dirs()
        logger.info("loading whisper model %s on %s (%s)", model_size, device, compute_type)
        _model_cache[key] = WhisperModel(model_size, device=device, compute_type=compute_type)
    return _model_cache[key]


def _is_gpu_oom(exc: Exception) -> bool:
    """Whether a GPU failure warrants the graceful CPU fallback.

    Covers true out-of-memory plus missing CUDA runtime libraries
    (cublas/cudnn not installed) — both degrade to CPU with a notice
    instead of failing the transcription.
    """
    text = str(exc).lower()
    return (
        "out of memory" in text
        or ("cuda" in text and "memory" in text)
        or ("not found or cannot be loaded" in text and ("cublas" in text or "cudnn" in text))
    )


def handle_transcribe(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """Transcribe an audio file; stream progress; apply vocab correction.

    Params: ``audio_path`` (required), ``model``/``device`` overrides,
    ``language`` hint. Returns raw + corrected transcripts, segments,
    detected language, durations, and the hardware actually used.
    """
    audio_path = params.get("audio_path", "")
    if not audio_path or not Path(audio_path).is_file():
        raise SidecarError("audio-not-found", f"There is no audio file at '{audio_path}'.")

    hardware = detect_hardware()
    device = params.get("device") or hardware["device"]
    model_size = params.get("model") or (GPU_MODEL if device == "cuda" else CPU_MODEL)
    compute_type = "float16" if device == "cuda" else "int8"

    ctx.emit_progress({"state": "loading-model", "model": model_size, "device": device})
    try:
        result = _run_transcription(model_size, device, compute_type, audio_path, params, ctx)
    except SidecarError:
        raise
    except Exception as exc:  # noqa: BLE001 - inspected for OOM fallback
        if device == "cuda" and _is_gpu_oom(exc):
            ctx.emit_progress(
                {
                    "state": "gpu-oom-fallback",
                    "note": "The GPU ran out of memory; retrying on CPU with the small model.",
                }
            )
            result = _run_transcription(CPU_MODEL, "cpu", "int8", audio_path, params, ctx)
            result["fallback"] = "gpu-oom"
        else:
            raise SidecarError(
                "transcription-failed",
                f"Transcription failed: {exc}. If this is a corrupt or unsupported "
                "file, re-export it as WAV or MP3 and try again.",
            ) from exc
    return result


def _run_transcription(
    model_size: str,
    device: str,
    compute_type: str,
    audio_path: str,
    params: dict[str, Any],
    ctx: RequestContext,
) -> dict[str, Any]:
    """One transcription pass on a specific device."""
    model = _load_model(model_size, device, compute_type)
    segments_iter, info = model.transcribe(
        audio_path,
        beam_size=5,
        vad_filter=True,
        language=params.get("language"),
    )
    duration = max(info.duration or 0.0, 0.001)
    texts: list[str] = []
    segments: list[dict[str, Any]] = []
    for segment in segments_iter:
        if ctx.check_cancelled():
            raise SidecarError("cancelled", "Transcription was cancelled.")
        texts.append(segment.text.strip())
        segments.append({"start": segment.start, "end": segment.end, "text": segment.text.strip()})
        ctx.emit_progress(
            {
                "state": "transcribing",
                "fraction": min(segment.end / duration, 1.0),
                "segment_text": segment.text.strip(),
            }
        )
    raw_transcript = " ".join(texts).strip()
    corrected, applied = vocab.correct(raw_transcript)
    return {
        "transcript": corrected,
        "raw_transcript": raw_transcript,
        "corrections": applied,
        "segments": segments,
        "language": info.language,
        "duration": info.duration,
        "device": device,
        "model": model_size,
    }


def handle_hardware(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """Report the detected ASR hardware path (used by first-run setup)."""
    return detect_hardware()
