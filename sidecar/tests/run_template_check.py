"""Phase 9 verification: all five templates differ on the same transcript.

Runs Stage 1 once on the fixture transcript, then Stage 2 once per template
preset, and asserts the five outputs are pairwise different in substance
(decision titles / chosen options / overview), not merely in wording.
"""

import json
import sys
import time
from pathlib import Path

from speakspec.pipeline import (
    load_preset,
    make_client,
    resolve_model,
    run_stage,
    stage1_message,
    stage2_message,
)

FIXTURES = Path(__file__).parent / "fixtures"
TEMPLATES = ["Solo MVP", "API service", "CLI tool", "Browser extension", "Data pipeline"]


def fingerprint(spec: dict) -> set[str]:
    """Substance fingerprint: decision titles + chosen options + language."""
    parts = {spec.get("recommended_language", {}).get("language", "")}
    for decision in spec.get("architecture_decisions", []):
        parts.add(decision.get("title", ""))
        parts.add(decision.get("chosen_option", ""))
    return {p.strip().lower() for p in parts if p.strip()}


def main() -> int:
    """Run the check and print the verdict."""
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
    for name in TEMPLATES:  # presets file must contain all five
        load_preset(name)

    transcript = (FIXTURES / "sample_transcript.txt").read_text(encoding="utf-8")
    client = make_client()
    model = resolve_model(None, client)
    print(f"model: {model}")

    stage1 = run_stage(1, stage1_message(transcript, ""), client=client, model=model)
    stage1_json = json.dumps(stage1.model_dump(), indent=1)

    specs: dict[str, dict] = {}
    for template in TEMPLATES:
        t0 = time.time()
        stage2 = run_stage(
            2,
            stage2_message(stage1_json, "", template),
            client=client,
            model=model,
            context=stage1.model_dump(),
        )
        specs[template] = stage2.model_dump()
        overview = specs[template]["system_overview"][:70].replace("\n", " ")
        print(f"  {template:18s} {time.time() - t0:4.0f}s  {overview}…")

    distinct_pairs = 0
    total_pairs = 0
    for i, a in enumerate(TEMPLATES):
        for b in TEMPLATES[i + 1 :]:
            total_pairs += 1
            fa, fb = fingerprint(specs[a]), fingerprint(specs[b])
            jaccard = len(fa & fb) / max(len(fa | fb), 1)
            different = jaccard < 0.8  # identical specs would be ~1.0
            distinct_pairs += 1 if different else 0
            verdict = "differs" if different else "SAME"
            print(f"  {a} vs {b}: substance overlap {jaccard:.2f} -> {verdict}")

    ok = distinct_pairs == total_pairs
    verdict = "PASS" if ok else "FAIL"
    print(f"\nTEMPLATES-DIFFER CHECK: {verdict} ({distinct_pairs}/{total_pairs} pairs differ)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
