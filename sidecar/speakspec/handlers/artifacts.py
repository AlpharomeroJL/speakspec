"""Artifact-writing handlers (AGENTS.md + CLAUDE.md with quality gate)."""

from pathlib import Path
from typing import Any

from speakspec.agents_md import write_agent_files
from speakspec.messages import SidecarError
from speakspec.rpc import RequestContext


def handle_write_agents_md(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """Gate and write AGENTS.md + CLAUDE.md from a Stage 3 bundle.

    Params: ``agents_md``, ``claude_md_shim``, ``file_tree``, ``dest_dir``.
    Returns the gate report (lines, commands, violations, pruned, written).
    """
    dest = params.get("dest_dir", "")
    if not dest:
        raise SidecarError("missing-dest", "dest_dir is required to write agent files.")
    report = write_agent_files(
        params.get("agents_md", ""),
        params.get("claude_md_shim", ""),
        params.get("file_tree", ""),
        Path(dest),
    )
    if report["missing_commands"]:
        ctx.emit_progress(
            {
                "state": "needs-commands",
                "missing": report["missing_commands"],
                "note": "Prompt the developer to supply the missing commands.",
            }
        )
    return report
