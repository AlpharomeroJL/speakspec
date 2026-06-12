"""Runtime model selection. Model names are never hardcoded in call sites.

Preference tiers live in ``config/models.json`` (repo) and can be replaced
via ``SPEAKSPEC_MODELS_CONFIG``. Selection: the configured default if it is
installed, else the first preference pattern (best tier the hardware allows)
matching an installed model, else the largest installed model.
"""

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from speakspec.config import repo_root
from speakspec.messages import SidecarError

if TYPE_CHECKING:
    from speakspec.ollama_client import OllamaClient


def models_config_path() -> Path:
    """Locate the model-tier preference config."""
    env = os.environ.get("SPEAKSPEC_MODELS_CONFIG")
    if env:
        return Path(env)
    return repo_root() / "config" / "models.json"


def load_model_tiers() -> dict:
    """Load tier definitions: name -> {min_vram_gb, patterns: [...]}."""
    with models_config_path().open(encoding="utf-8") as fh:
        return json.load(fh)["tiers"]


def _matches(installed_name: str, pattern: str) -> bool:
    """Prefix match on the base name, ignoring tag granularity.

    Pattern ``qwen3:8b`` matches ``qwen3:8b`` and ``qwen3:8b-q4_K_M``;
    pattern ``phi4-mini`` matches any ``phi4-mini*`` tag.
    """
    return installed_name.lower().startswith(pattern.lower())


def choose_model(
    installed: list[dict],
    preferred: str | None = None,
    vram_gb: float | None = None,
) -> str:
    """Pick the model to use from ``/api/tags`` output.

    ``preferred`` (config/user choice) wins when installed. Otherwise walk
    tiers best-first, skipping tiers the known VRAM cannot hold, and return
    the first installed match. Fall back to the largest installed model.
    """
    if not installed:
        raise SidecarError(
            "no-models-installed",
            "No Ollama models are installed. Pull one (for example a Qwen 3 or "
            "Gemma 4 class model) from the model setup screen before running "
            "the pipeline.",
        )
    names = [m["name"] for m in installed]
    if preferred:
        for name in names:
            if _matches(name, preferred):
                return name

    tiers = load_model_tiers()
    # Best tier first: power_user > default > fast_fallback.
    for tier_name in ("power_user", "default", "fast_fallback"):
        tier = tiers.get(tier_name)
        if tier is None:
            continue
        if vram_gb is not None and vram_gb < tier.get("min_vram_gb", 0):
            continue
        for pattern in tier["patterns"]:
            for name in names:
                if _matches(name, pattern):
                    return name

    largest = max(installed, key=lambda m: m.get("size", 0))
    return largest["name"]


def choose_fast_model(
    installed: list[dict],
    preferred: str | None = None,
    vram_gb: float | None = None,
) -> str:
    """Pick the best installed model from the fast_fallback tier."""
    if not installed:
        raise SidecarError(
            "no-models-installed",
            "No Ollama models are installed. Pull a fast fallback model "
            "(Phi-4-mini or Gemma 4 4B class) before enabling fast pipeline.",
        )
    tiers = load_model_tiers()
    tier = tiers.get("fast_fallback", {})
    for pattern in tier.get("patterns", []):
        for model in installed:
            if _matches(model["name"], pattern):
                return model["name"]
    return choose_model(installed, preferred=preferred, vram_gb=vram_gb)


def resolve_stage_model(
    stage: int,
    explicit: str | None,
    client: "OllamaClient",  # noqa: F821
) -> str:
    """Resolve the model for a pipeline stage, honoring fast_pipeline settings."""
    from speakspec.config import get_config

    config = get_config()
    installed = client.list_models()
    preferred = explicit or config.get("default_model")
    if config.get("fast_pipeline") and stage in (1, 3):
        return choose_fast_model(installed, preferred=preferred)
    return choose_model(installed, preferred=preferred)


def resolve_repair_model(client: "OllamaClient") -> str:  # noqa: F821
    """Pick a small fast model for diagram repair calls."""
    from speakspec.config import get_config

    config = get_config()
    installed = client.list_models()
    if config.get("fast_pipeline"):
        return choose_fast_model(installed, preferred=config.get("default_model"))
    return choose_fast_model(installed, preferred=config.get("default_model"))
