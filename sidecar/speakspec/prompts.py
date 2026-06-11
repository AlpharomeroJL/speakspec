"""Loader for the locked stage prompts in ``docs/prompts/stage-prompts.md``.

The markdown file is the single source of truth (product IP). This module
extracts each stage's system prompt and user-message template from its fixed
structure rather than duplicating the text in code.
"""

import os
import re
from functools import lru_cache
from pathlib import Path

_STAGE_HEADER = re.compile(r"^## STAGE (\d) ", re.MULTILINE)
_SYSTEM_MARKER = "**System prompt:**"
_TEMPLATE_MARKER = "**User message template:**"
_FENCE = re.compile(r"```\n(.*?)```", re.DOTALL)


def prompts_file() -> Path:
    """Locate stage-prompts.md (env override > repo layout)."""
    env = os.environ.get("SPEAKSPEC_PROMPTS_FILE")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "docs" / "prompts" / "stage-prompts.md"


@lru_cache(maxsize=1)
def _sections() -> dict[int, str]:
    """Split the prompts file into one text section per stage."""
    text = prompts_file().read_text(encoding="utf-8")
    matches = list(_STAGE_HEADER.finditer(text))
    if len(matches) != 3:
        raise ValueError(
            f"stage-prompts.md must contain exactly 3 '## STAGE n' sections, found {len(matches)}"
        )
    sections: dict[int, str] = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[int(match.group(1))] = text[match.start() : end]
    return sections


def system_prompt(stage: int) -> str:
    """Return the locked system prompt for ``stage`` (1, 2, or 3)."""
    section = _sections()[stage]
    start = section.index(_SYSTEM_MARKER) + len(_SYSTEM_MARKER)
    end = section.index(_TEMPLATE_MARKER)
    return section[start:end].strip()


def user_message(stage: int, **values: str) -> str:
    """Render the stage's user-message template with ``values``."""
    section = _sections()[stage]
    after_marker = section[section.index(_TEMPLATE_MARKER) :]
    fence = _FENCE.search(after_marker)
    if fence is None:
        raise ValueError(f"no fenced user-message template found for stage {stage}")
    return fence.group(1).strip().format(**values)
