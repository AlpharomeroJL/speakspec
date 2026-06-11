"""RELEASE GATE: 20-spec Mermaid corpus — zero invalid diagrams allowed.

For every corpus spec: run real Stage 3 against Ollama, then the
validate-and-repair loop, then independently re-parse every final diagram
with the real Mermaid 11 parser. Any diagram that fails the final re-parse
fails the gate. Stubbed diagrams parse (stubs are valid Mermaid) and are
reported, honestly, as stubs.

Run: ``python tests/run_mermaid_corpus.py`` (from ``sidecar/``). Slow: one
Stage 3 generation per spec.
"""

import json
import sys
import time
from collections import Counter
from pathlib import Path

from speakspec.mermaid_repair import DIAGRAM_KINDS, get_validator, validate_and_repair_bundle
from speakspec.pipeline import make_client, resolve_model, run_stage, stage3_message

CORPUS_DIR = Path(__file__).parent / "fixtures" / "corpus"


def main() -> int:
    """Run the corpus; print per-spec results and the final verdict."""
    # UTF-8 + line buffering: progress visible while detached, and error
    # snippets (which may contain any character) never crash the gate.
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
    validator = get_validator()
    if not validator.available:
        print("FATAL: the release gate requires Node + the mermaid validator.")
        return 2

    specs = sorted(CORPUS_DIR.glob("spec_*.json"))
    if len(specs) != 20:
        print(f"FATAL: expected 20 corpus specs, found {len(specs)}. Run gen_corpus.py.")
        return 2
    # Optional slice (1-based, inclusive) to resume an interrupted gate run.
    if len(sys.argv) == 3:
        start, end = int(sys.argv[1]), int(sys.argv[2])
        specs = specs[start - 1 : end]
        print(f"running corpus slice {start}..{end} ({len(specs)} specs)")

    client = make_client()
    model = resolve_model(None, client)
    print(f"model: {model}  specs: {len(specs)}")

    invalid_total = 0
    status_counter: Counter[str] = Counter()
    for path in specs:
        spec = json.loads(path.read_text(encoding="utf-8"))
        t0 = time.time()
        bundle = run_stage(
            3, stage3_message(json.dumps(spec, indent=1)), client=client, model=model
        )
        finals, reports = validate_and_repair_bundle(
            bundle.diagrams.model_dump(), client=client, model=model
        )
        # Independent final re-parse: the actual gate.
        bad_kinds = []
        for kind in DIAGRAM_KINDS:
            if not validator.check(finals[kind])["ok"]:
                bad_kinds.append(kind)
        invalid_total += len(bad_kinds)
        statuses = {r["kind"]: r["status"] for r in reports}
        status_counter.update(statuses.values())
        verdict = "OK " if not bad_kinds else "BAD"
        print(
            f"[{verdict}] {path.stem:42s} {time.time() - t0:5.0f}s "
            f"{json.dumps(statuses)}" + (f"  INVALID: {bad_kinds}" if bad_kinds else "")
        )
        for r in reports:
            if r["status"] == "stubbed":
                last_err = (r["errors"][-1] if r["errors"] else "")[:200].replace("\n", " ⏎ ")
                print(f"      stubbed {r['kind']} (final error): {last_err}")

    total = len(specs) * len(DIAGRAM_KINDS)
    print(f"\ndiagram outcomes across {total}: {dict(status_counter)}")
    print(f"invalid diagrams after repair: {invalid_total}")
    print(f"MERMAID RELEASE GATE: {'PASS' if invalid_total == 0 else 'FAIL'}")
    return 0 if invalid_total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
