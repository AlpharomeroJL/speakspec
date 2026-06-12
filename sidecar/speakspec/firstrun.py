"""First-run support (Phase 10): hardware report and model download.

``system.hardware`` answers in well under five seconds: ASR device probe,
GPU VRAM via nvidia-smi when present, Ollama reachability, installed models,
and the tier recommendation for this machine. ``models.pull`` streams
download progress (percent + bytes; Ollama resumes interrupted layers).
"""

import logging
import shutil
import subprocess
from typing import Any

from speakspec.asr import detect_hardware
from speakspec.config import get_config
from speakspec.messages import SidecarError
from speakspec.model_select import choose_model, load_model_tiers
from speakspec.ollama_client import OllamaClient
from speakspec.rpc import RequestContext

logger = logging.getLogger(__name__)


def detect_vram_gb() -> float | None:
    """Total VRAM of the first NVIDIA GPU, or None without one."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=4,
            check=True,
        )
        first = out.stdout.strip().splitlines()[0]
        return round(float(first) / 1024, 1)
    except (subprocess.SubprocessError, ValueError, IndexError):
        return None


def recommend_tier(vram_gb: float | None) -> str:
    """Pick the model tier this machine can comfortably run."""
    tiers = load_model_tiers()
    if vram_gb is not None:
        for name in ("power_user", "default", "fast_fallback"):
            tier = tiers.get(name)
            if tier and vram_gb >= tier.get("min_vram_gb", 0):
                return name
    return "fast_fallback"


def handle_system_hardware(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """Full first-run hardware report (must complete within 5 seconds)."""
    asr = detect_hardware()
    config = get_config()
    vram = config.get("vram_override_gb")
    if vram is None:
        vram = detect_vram_gb()
    client = OllamaClient(get_config()["ollama_url"])
    ollama_ok = True
    installed: list[dict] = []
    selected: str | None = None
    try:
        installed = client.list_models()
        if installed:
            selected = choose_model(installed, preferred=get_config()["default_model"])
    except SidecarError:
        ollama_ok = False
    tier = recommend_tier(vram)
    tiers = load_model_tiers()
    return {
        "asr": asr,
        "vram_gb": vram,
        "ollama_reachable": ollama_ok,
        "installed_models": [m["name"] for m in installed],
        "selected_model": selected,
        "recommended_tier": tier,
        "tier_patterns": tiers.get(tier, {}).get("patterns", []),
        "install_hint": None
        if ollama_ok
        else "Install Ollama from https://ollama.com/download, start it, and retry.",
    }


def handle_models_pull(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """Pull a model with streamed percent progress (resumable)."""
    name = params.get("name", "")
    if not name:
        raise SidecarError("missing-model-name", "models.pull needs a model name.")
    client = OllamaClient(get_config()["ollama_url"])

    def forward(obj: dict) -> None:
        total = obj.get("total") or 0
        completed = obj.get("completed") or 0
        ctx.emit_progress(
            {
                "state": "pulling",
                "model": name,
                "status": obj.get("status", ""),
                "total": total,
                "completed": completed,
                "percent": round(completed * 100 / total, 1) if total else None,
            }
        )

    client.pull_model(name, on_progress=forward, cancelled=ctx.check_cancelled)
    return {"pulled": name}
