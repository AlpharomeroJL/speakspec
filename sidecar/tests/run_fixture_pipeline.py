"""Phase 4 verification: run the full pipeline on the fixture transcript.

Drives Stage 1 -> interview-back injection -> Stage 2 -> Stage 3 against the
real local Ollama, prints all three validated JSON outputs, and asserts the
phase gates:

* Stage 1 intent_summary is shorter than the raw transcript,
* every Stage 2 decision has at least one ruled-out alternative,
* Stage 3 emits every required artifact.

Run: ``python tests/run_fixture_pipeline.py`` (from ``sidecar/``).
"""

import json
import sys
import time
from pathlib import Path

from speakspec.pipeline import (
    make_client,
    resolve_model,
    run_stage,
    stage1_message,
    stage2_message,
    stage3_message,
)

FIXTURES = Path(__file__).parent / "fixtures"


def main() -> int:
    """Run the pipeline end-to-end and print the verification verdicts."""
    transcript = (FIXTURES / "sample_transcript.txt").read_text(encoding="utf-8")
    answers = (FIXTURES / "sample_interview_answers.txt").read_text(encoding="utf-8")

    client = make_client()
    model = resolve_model(None, client)
    print(f"== model: {model}", file=sys.stderr)

    t0 = time.time()
    stage1 = run_stage(1, stage1_message(transcript, ""), client=client, model=model)
    print(f"== stage 1 done in {time.time() - t0:.0f}s", file=sys.stderr)
    print("\n===== STAGE 1 OUTPUT (validated) =====")
    print(json.dumps(stage1.model_dump(), indent=2))

    print("\n===== INTERVIEW QUESTIONS ASKED =====", file=sys.stderr)
    for q in stage1.interview_questions:
        print(f"  - {q.question}", file=sys.stderr)
    print("== injecting fixture interview answers into Stage 2", file=sys.stderr)

    t0 = time.time()
    stage2 = run_stage(
        2,
        stage2_message(json.dumps(stage1.model_dump(), indent=1), answers, "Solo MVP"),
        client=client,
        model=model,
    )
    print(f"== stage 2 done in {time.time() - t0:.0f}s", file=sys.stderr)
    print("\n===== STAGE 2 OUTPUT (validated) =====")
    print(json.dumps(stage2.model_dump(), indent=2))

    t0 = time.time()
    stage3 = run_stage(
        3,
        stage3_message(json.dumps(stage2.model_dump(), indent=1)),
        client=client,
        model=model,
    )
    print(f"== stage 3 done in {time.time() - t0:.0f}s", file=sys.stderr)
    print("\n===== STAGE 3 OUTPUT (validated) =====")
    print(json.dumps(stage3.model_dump(), indent=2))

    print("\n===== PHASE 4 GATES =====")
    summary_shorter = len(stage1.intent_summary) < len(transcript)
    print(
        f"stage1 intent_summary shorter than transcript: {summary_shorter} "
        f"({len(stage1.intent_summary)} vs {len(transcript)} chars)"
    )
    ruled_out_ok = all(len(d.ruled_out) >= 1 for d in stage2.architecture_decisions)
    print(
        f"every stage2 decision has >=1 ruled_out: {ruled_out_ok} "
        f"({len(stage2.architecture_decisions)} decisions)"
    )
    artifacts = {
        "agents_md": bool(stage3.agents_md.strip()),
        "claude_md_shim": bool(stage3.claude_md_shim.strip()),
        "adrs": len(stage3.adrs) >= 1,
        "diagrams": all(
            bool(getattr(stage3.diagrams, k).strip())
            for k in ("sequence", "er", "component", "c4_context", "c4_container")
        ),
        "file_tree": bool(stage3.file_tree.strip()),
        "first_pr": len(stage3.first_pr.tasks) >= 1,
    }
    print(f"stage3 artifacts present: {artifacts}")

    ok = summary_shorter and ruled_out_ok and all(artifacts.values())
    print(f"\nPHASE 4 VERIFY: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
