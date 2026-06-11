"""RELEASE GATE: AGENTS.md across 5 project types — <200 lines, command-complete.

For each of five fixture transcripts (web app, CLI tool, browser extension,
data pipeline, API service): run Stages 1 -> 2 -> 3 against the real model
with the matching template preset, gate + write AGENTS.md and CLAUDE.md, and
assert every output is under 200 lines with build/test/run commands present.

Run: ``python tests/run_agents_gate.py`` (from ``sidecar/``). Slow: three
generations per project type.
"""

import json
import sys
import time
from pathlib import Path

from speakspec.agents_md import write_agent_files
from speakspec.pipeline import (
    ensure_real_agents_md,
    make_client,
    resolve_model,
    run_stage,
    stage1_message,
    stage2_message,
    stage3_message,
)

FIXTURES = Path(__file__).parent / "fixtures"
OUT_DIR = Path(__file__).parent / "out" / "agents_gate"

PROJECTS = [
    ("gym-routes-webapp", FIXTURES / "sample_transcript.txt", "Solo MVP"),
    ("photo-renamer-cli", FIXTURES / "transcripts" / "cli_tool.txt", "CLI tool"),
    (
        "price-watch-extension",
        FIXTURES / "transcripts" / "browser_extension.txt",
        "Browser extension",
    ),
    ("air-quality-pipeline", FIXTURES / "transcripts" / "data_pipeline.txt", "Data pipeline"),
    ("booking-api", FIXTURES / "transcripts" / "api_service.txt", "API service"),
]


def main() -> int:
    """Run the gate across all five project types; print the verdicts."""
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
    client = make_client()
    model = resolve_model(None, client)
    print(f"model: {model}")
    failures = 0

    projects = PROJECTS
    # Optional slice (1-based, inclusive) to resume an interrupted gate run.
    if len(sys.argv) == 3:
        start, end = int(sys.argv[1]), int(sys.argv[2])
        projects = PROJECTS[start - 1 : end]
        print(f"running gate slice {start}..{end} ({len(projects)} projects)")

    for name, transcript_path, template in projects:
        t0 = time.time()
        transcript = transcript_path.read_text(encoding="utf-8")
        stage1 = run_stage(1, stage1_message(transcript, ""), client=client, model=model)
        stage2 = run_stage(
            2,
            stage2_message(json.dumps(stage1.model_dump(), indent=1), "", template),
            client=client,
            model=model,
        )
        spec_json = json.dumps(stage2.model_dump(), indent=1)
        stage3 = run_stage(3, stage3_message(spec_json), client=client, model=model)
        stage3 = ensure_real_agents_md(stage3, spec_json, client=client, model=model)
        report = write_agent_files(
            stage3.agents_md, stage3.claude_md_shim, stage3.file_tree, OUT_DIR / name
        )
        ok = report["under_cap"] and report["command_complete"]
        failures += 0 if ok else 1
        print(
            f"[{'OK ' if ok else 'BAD'}] {name:24s} template={template:18s} "
            f"lines={report['lines']:3d} pruned={report['pruned']} "
            f"missing={report['missing_commands']} ({time.time() - t0:.0f}s)"
        )

    print("\nPaste-test instructions (manual verification):")
    print(f"  1. Open {OUT_DIR}/<project>/AGENTS.md")
    print("  2. Claude Code: copy AGENTS.md + CLAUDE.md into an empty repo, run")
    print("     `claude` and ask it to start task 1; it should know the commands")
    print("     and constraints without further explanation.")
    print("  3. Cursor: add AGENTS.md as project rules (rename .cursorrules or")
    print("     reference it) and confirm the agent quotes the build/run commands.")
    print(f"\nAGENTS.MD RELEASE GATE: {'PASS' if failures == 0 else f'FAIL ({failures} of 5)'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
