#!/usr/bin/env python3
"""Benchmark pipeline stage timings for release verification."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / "sidecar"
sys.path.insert(0, str(SIDECAR))

from speakspec.pipeline import (  # noqa: E402
    make_client,
    resolve_stage_model,
    run_stage,
    stage1_message,
    stage2_message,
    stage3_message,
)

FIXTURE = SIDECAR / "tests" / "fixtures" / "examples" / "stage1_example.json"


def main() -> int:
    transcript = "Build a local-first task tracker with SQLite and a Solid.js UI."
    client = make_client()
    model_s1 = resolve_stage_model(1, None, client)
    model_s2 = resolve_stage_model(2, None, client)
    model_s3 = resolve_stage_model(3, None, client)

    t0 = time.time()
    s1 = run_stage(1, stage1_message(transcript, ""), client=client, model=model_s1)
    t1 = time.time()
    constraints = s1.model_dump()
    s2 = run_stage(
        2,
        stage2_message(json.dumps(constraints, indent=1), "", "Solo MVP"),
        client=client,
        model=model_s2,
        context=constraints,
    )
    t2 = time.time()
    spec = s2.model_dump()
    s3 = run_stage(
        3,
        stage3_message(json.dumps(spec, indent=1)),
        client=client,
        model=model_s3,
    )
    t3 = time.time()

    print(f"Stage 1 ({model_s1}): {t1 - t0:.1f}s")
    print(f"Stage 2 ({model_s2}): {t2 - t1:.1f}s")
    print(f"Stage 3 ({model_s3}): {t3 - t2:.1f}s")
    print(f"Total: {t3 - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
