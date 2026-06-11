"""Unit tests for the AGENTS.md quality gate (no model needed)."""

from speakspec.agents_md import (
    MAX_LINES,
    apply_gate,
    detect_commands,
    find_violations,
    gate_report,
    normalize_shim,
    prune,
)

GOOD_DOC = """# Demo

One-line description.

## Tech stack
- Python 3.12, FastAPI 0.115

## Commands
- build: `pip install -r requirements.txt`
- test: `pytest`
- run: `uvicorn app.main:app`

## Key directories
- `app/` — start at `app/main.py`

## Hard constraints
- One process serves everything

## Do not
- Do not add an SPA build chain

## First tasks
1. Scaffold the app

## Open questions
- None
"""

TREE = """demo/
├── app/
│   └── main.py   # entry
└── requirements.txt
"""


def test_good_doc_passes_gate() -> None:
    report = gate_report(GOOD_DOC, TREE)
    assert report["passes"], report
    assert report["command_complete"]
    assert report["under_cap"]


def test_detects_missing_test_command() -> None:
    doc = GOOD_DOC.replace("- test: `pytest`\n", "")
    report = gate_report(doc, TREE)
    assert "test" in report["missing_commands"]
    assert not report["passes"]


def test_detects_file_tree_prose_and_prunes_it() -> None:
    prose = (
        "The main.py file contains the FastAPI application entry point and "
        "wires together every router, middleware, and startup hook for the demo.\n"
    )
    doc = GOOD_DOC + prose
    violations = find_violations(doc, TREE)
    assert any(v["kind"] == "file-tree-prose" for v in violations)
    final, report = apply_gate(doc, TREE)
    assert report["pruned"] is True
    assert "wires together every router" not in final
    assert report["passes"], report


def test_detects_linter_duplication() -> None:
    doc = GOOD_DOC + "\n- Keep line length under 100 characters\n"
    violations = find_violations(doc, TREE)
    assert any(v["kind"] == "linter-duplication" for v in violations)


def test_prune_brings_oversized_doc_under_cap_keeping_commands() -> None:
    filler = "\n".join(f"Background paragraph number {i} with plenty of words." for i in range(300))
    doc = GOOD_DOC + "\n## Notes\n" + filler + "\n"
    final, report = apply_gate(doc, TREE)
    assert report["under_cap"], f"still {report['lines']} lines"
    assert report["lines"] < MAX_LINES
    for cmd in ("pip install", "pytest", "uvicorn"):
        assert cmd in final, f"pruning lost the {cmd} command"


def test_prune_is_idempotent_on_good_doc() -> None:
    assert prune(GOOD_DOC, TREE).strip() == GOOD_DOC.strip()


def test_command_detection_handles_label_and_backtick_styles() -> None:
    doc = "build: cargo check --all\n- `go test ./...`\n- run: `node server.js`\n"
    commands = detect_commands(doc)
    assert commands["build"] and commands["test"] and commands["run"]


def test_shim_normalization() -> None:
    assert normalize_shim("  @AGENTS.md  \n") == "@AGENTS.md\n"
    assert normalize_shim("") == "@AGENTS.md\n"
    override = "@AGENTS.md\n\nUse the Claude-specific MCP config in .claude/.\n"
    assert normalize_shim(override) == override
