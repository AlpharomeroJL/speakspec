"""Technical vocabulary correction: post-ASR, pre-Stage-1.

Fixes framework/library names the ASR mishears ("fast api" -> "FastAPI")
using the community-editable dictionary at ``dicts/tech-vocab.json``.
Matching is case-insensitive on whole-word boundaries, longest phrase first,
and must never alter non-technical words (enforced by a clean-text corpus
test).
"""

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from speakspec.config import repo_root


def vocab_file() -> Path:
    """Locate the dictionary (env override > repo layout)."""
    env = os.environ.get("SPEAKSPEC_VOCAB_FILE")
    if env:
        return Path(env)
    return repo_root() / "dicts" / "tech-vocab.json"


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[re.Pattern[str], str]]:
    """Compile the dictionary into (pattern, replacement) pairs."""
    with vocab_file().open(encoding="utf-8") as fh:
        corrections: dict[str, str] = json.load(fh)["corrections"]
    pairs: list[tuple[re.Pattern[str], str]] = []
    # Longest first so "post gress sequel" wins over "post gress".
    for wrong in sorted(corrections, key=len, reverse=True):
        pattern = re.compile(rf"\b{re.escape(wrong)}\b", re.IGNORECASE)
        pairs.append((pattern, corrections[wrong]))
    return pairs


def correct(text: str) -> tuple[str, list[dict[str, str]]]:
    """Apply the dictionary to ``text``.

    Returns the corrected text and the list of applied corrections
    (``{"from": ..., "to": ..., "count": ...}``), so the UI can show what
    changed and the raw transcript stays recoverable.
    """
    applied: list[dict[str, str]] = []
    result = text
    for pattern, replacement in _compiled():
        result, count = pattern.subn(replacement, result)
        if count:
            applied.append({"from": pattern.pattern, "to": replacement, "count": str(count)})
    return result, applied
