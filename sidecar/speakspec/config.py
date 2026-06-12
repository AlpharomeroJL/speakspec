"""Sidecar configuration: defaults, optional config file, env overrides.

Nothing machine-specific is hardcoded. Resolution order per key:
environment variable > JSON config file (``SPEAKSPEC_CONFIG``) > default.
"""

import json
import os
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    # Contract C endpoint. Localhost only unless the user reconfigures.
    "ollama_url": "http://localhost:11434",
    # None means: auto-select the best installed model (see model_select.py).
    "default_model": None,
    # Bounds for the always-explicit num_ctx (see pipeline.size_num_ctx).
    "num_ctx_min": 8192,
    "num_ctx_max": 32768,
    # ASR device override: auto, cuda, or cpu.
    "asr_device": "auto",
    # Manual VRAM override for tier recommendation (GB).
    "vram_override_gb": None,
    # Skip interview questions automatically when true.
    "interview_auto_mode": False,
    # Optional cloud Stage 3 (off by default).
    "cloud_stage3_enabled": False,
    "cloud_provider": "openai",
    "cloud_api_key": None,
    # Use fast_fallback tier models for S1/S3/repairs when true.
    "fast_pipeline": False,
}

_ENV_KEYS = {
    "ollama_url": "SPEAKSPEC_OLLAMA_URL",
    "default_model": "SPEAKSPEC_DEFAULT_MODEL",
}


def repo_root() -> Path:
    """Repo root in the dev layout (``sidecar/`` parent)."""
    return Path(__file__).resolve().parents[2]


def templates_dir() -> Path:
    """Directory holding presets and the OSS knowledge base."""
    env = os.environ.get("SPEAKSPEC_TEMPLATES_DIR")
    if env:
        return Path(env)
    return repo_root() / "templates"


def get_config() -> dict[str, Any]:
    """Build the effective configuration dictionary."""
    config = dict(DEFAULTS)
    config_path = os.environ.get("SPEAKSPEC_CONFIG")
    if config_path and Path(config_path).is_file():
        with Path(config_path).open(encoding="utf-8") as fh:
            config.update(json.load(fh))
    for key, env_name in _ENV_KEYS.items():
        value = os.environ.get(env_name)
        if value:
            config[key] = value
    return config
