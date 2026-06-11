"""Export bundle tests using the checked-in stage 2/3 examples."""

import json
import zipfile
from pathlib import Path

from speakspec.exports import render_markdown, write_bundle

FIXTURES = Path(__file__).parent / "fixtures" / "examples"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_markdown_export_contains_all_sections() -> None:
    stage2 = _load("stage2_example.json")
    stage3 = _load("stage3_example.json")
    markdown = render_markdown(stage2, stage3)
    for heading in (
        "## Recommended language",
        "## Architecture decisions",
        "## What not to build",
        "## Diagrams",
        "```mermaid",
        "## Suggested file tree",
        "## First PR",
    ):
        assert heading in markdown, f"missing {heading}"
    # All five diagrams inline.
    assert markdown.count("```mermaid") == 5


def test_write_bundle_writes_everything(tmp_path: Path) -> None:
    stage2 = _load("stage2_example.json")
    stage3 = _load("stage3_example.json")
    result = write_bundle(tmp_path, stage2, stage3, [{"kind": "sequence", "status": "valid"}])

    expected = [
        "AGENTS.md",
        "CLAUDE.md",
        "spec.md",
        "spec.docx",
        "spec.json",
        "diagrams/sequence.mmd",
        "diagrams/c4_container.mmd",
        "docs/adr/0001-single-server-rendered-web-app.md",
    ]
    for rel in expected:
        assert (tmp_path / rel).is_file(), f"missing {rel}"

    # The DOCX is a real Word file (a ZIP with the document part).
    with zipfile.ZipFile(tmp_path / "spec.docx") as zf:
        assert "word/document.xml" in zf.namelist()

    # The gate ran and the example passes it.
    assert result["agents_gate"]["passes"] is True
    # spec.json round-trips.
    payload = json.loads((tmp_path / "spec.json").read_text(encoding="utf-8"))
    assert payload["diagram_reports"][0]["status"] == "valid"


def test_claude_md_is_the_shim(tmp_path: Path) -> None:
    stage2 = _load("stage2_example.json")
    stage3 = _load("stage3_example.json")
    write_bundle(tmp_path, stage2, stage3)
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "@AGENTS.md\n"
