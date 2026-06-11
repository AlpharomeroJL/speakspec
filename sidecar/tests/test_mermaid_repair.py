"""Mermaid repair loop tests: sanitizer, stubs, loop order, real parser.

Tests that need the real parser skip cleanly when Node is unavailable, but
on dev/CI machines (and for the release gate) they run for real.
"""

import pytest

from speakspec.mermaid_repair import (
    DIAGRAM_KINDS,
    STUBS,
    MermaidValidator,
    normalize_frame,
    repair_diagram,
    sanitize,
)

validator = MermaidValidator()
needs_parser = pytest.mark.skipif(
    not validator.available, reason="node / validator script not available"
)


def test_normalize_frame_strips_fences_and_init() -> None:
    fenced = "```mermaid\ngraph TD\n  a --> b\n```"
    assert normalize_frame(fenced) == "graph TD\n  a --> b"
    themed = "%%{init: {'theme':'dark'}}%%\ngraph TD\n  a --> b"
    assert normalize_frame(themed) == "graph TD\n  a --> b"


def test_sanitize_quotes_paren_labels() -> None:
    out = sanitize("graph TD\n  a[OAuth (Google)] --> b[End]")
    assert 'a["OAuth (Google)"]' in out


def test_sanitize_fixes_arrows_and_fullwidth() -> None:
    out = sanitize("graph TD\n  a[Start] -> b[Stop]")
    assert "a[Start] --> b[Stop]" in out
    out2 = sanitize("graph TD\n  a[输入（数据）] --> b[End]")
    assert "（" not in out2 and "）" not in out2


def test_sanitize_leaves_valid_sequence_arrows_alone() -> None:
    src = "sequenceDiagram\n  Alice->>Bob: hi\n  Bob-->>Alice: yo"
    assert sanitize(src) == src


@needs_parser
def test_real_parser_accepts_good_and_rejects_bad() -> None:
    good = validator.check("graph TD\n  a[Start] --> b[End]")
    assert good["ok"] is True
    bad = validator.check("graph TD\n  a[OAuth (Google)] --> b")
    assert bad["ok"] is False
    assert "Parse error" in bad["error"]


@needs_parser
@pytest.mark.parametrize("kind", DIAGRAM_KINDS)
def test_every_stub_is_valid_mermaid(kind: str) -> None:
    verdict = validator.check(STUBS[kind])
    assert verdict["ok"] is True, f"stub for {kind} failed: {verdict.get('error')}"


@needs_parser
@pytest.mark.parametrize("kind", DIAGRAM_KINDS)
def test_every_repair_skeleton_is_valid_mermaid(kind: str) -> None:
    from speakspec.mermaid_repair import KIND_RULES

    verdict = validator.check(KIND_RULES[kind]["skeleton"])
    assert verdict["ok"] is True, f"skeleton for {kind} failed: {verdict.get('error')}"


@needs_parser
def test_sanitizer_fixes_wrong_header_token() -> None:
    # The exact pseudo-Mermaid qwen3:8b produced in the first corpus run.
    broken = (
        "sequence\n\nparticipant GymService\nparticipant Member\n\n"
        "GymService -> Member: Log route\nMember --> GymService: Feedback"
    )
    fixed = sanitize(broken, "sequence")
    assert fixed.startswith("sequenceDiagram")
    assert validator.check(fixed)["ok"], fixed


@needs_parser
def test_sanitizer_converts_er_entity_dialect() -> None:
    # Exact dialect observed in the corpus run: entity/attribute keywords.
    broken = (
        "er\n\nentity Recipe\nattribute id\nattribute name\n\n"
        "entity Ingredient\nattribute id\n\nRecipe has Ingredient"
    )
    fixed = sanitize(broken, "er")
    assert fixed.startswith("erDiagram")
    assert validator.check(fixed)["ok"], fixed
    assert "RECIPE" in fixed and "INGREDIENT" in fixed


@needs_parser
def test_sanitizer_converts_component_pseudo_dialect() -> None:
    # Exact failure: wrong header, multi-word bare ids, sequence-style labels.
    broken = (
        "componentDiagram\nMQTT Broker Bridge --> Rule Engine: Forward data\n"
        "Rule Engine --> Alert Dispatcher: Trigger alerts"
    )
    fixed = sanitize(broken, "component")
    assert fixed.startswith("graph TD")
    assert validator.check(fixed)["ok"], fixed
    assert "MQTT Broker Bridge" in fixed  # label preserved


@needs_parser
def test_sanitizer_converts_c4_system_dialect() -> None:
    broken = (
        "c4Container\nsystem Web App\nsystem Merge Engine (pint)\n"
        "user Member\nexternal Google Sheets\nWeb App uses Merge Engine (pint)\n"
        "Member uses Web App"
    )
    fixed = sanitize(broken, "c4_container")
    assert fixed.startswith("C4Container")
    assert validator.check(fixed)["ok"], fixed
    assert "Merge Engine" in fixed


@needs_parser
def test_sanitizer_handles_bare_names_and_paren_edge_labels() -> None:
    # The two remaining corpus failure shapes from run 4.
    broken = (
        "component\n"
        "component Widget (embed.js)\n"
        "Reply Router\n"
        "Agent Console\n"
        "Widget (embed.js) --> Reply Router: Fetch (cached) reply\n"
        "Reply Router --> Agent Console"
    )
    fixed = sanitize(broken, "component")
    assert validator.check(fixed)["ok"], fixed
    assert "Widget (embed.js)" in fixed
    assert '"Fetch (cached) reply"' in fixed


@needs_parser
def test_sanitizer_converts_er_arrow_relationships() -> None:
    broken = "er\nentity Sensor\nentity Reading\nSensor --> Reading"
    fixed = sanitize(broken, "er")
    assert validator.check(fixed)["ok"], fixed
    assert "SENSOR ||--o{ READING" in fixed


@needs_parser
def test_repair_falls_back_to_sanitizing_the_original() -> None:
    class ManglingClient:
        """Model repairs that replace a convertible dialect with junk."""

        def chat_structured(self, **kwargs) -> str:
            return '{"mermaid": "graph TD\\n  ]][[ worse than before ((("}'

    original = "component\ncomponent WebApp\ncomponent MergeEngine\nWebApp --> MergeEngine: merge"
    final, report = repair_diagram(
        "component", original, validator=validator, client=ManglingClient(), model="fake"
    )
    assert report["status"] == "sanitized"
    assert validator.check(final)["ok"]
    assert "WebApp" in final  # meaning survived via the original source


@needs_parser
def test_echo_repair_falls_through_to_sanitizer() -> None:
    class EchoClient:
        """Worst case: model returns the broken source unchanged."""

        def chat_structured(self, **kwargs) -> str:
            import json as _json
            import re as _re

            src = _re.search(r"INVALID SOURCE.*?:\n(.*)", kwargs["user"], _re.DOTALL)
            return _json.dumps({"mermaid": src.group(1) if src else ""})

    broken = "sequence\n\nparticipant A\nparticipant B\n\nA -> B: hi"
    final, report = repair_diagram(
        "sequence", broken, validator=validator, client=EchoClient(), model="fake"
    )
    assert report["status"] == "sanitized"
    assert validator.check(final)["ok"]


@needs_parser
def test_repair_loop_valid_source_passes_through() -> None:
    src = "sequenceDiagram\n  A->>B: ping"
    final, report = repair_diagram("sequence", src, validator=validator)
    assert report["status"] == "valid"
    assert final == src


@needs_parser
def test_repair_loop_sanitizer_rescues_without_model() -> None:
    src = "graph TD\n  a[OAuth (Google)] --> b[End]"
    final, report = repair_diagram("component", src, validator=validator)
    assert report["status"] == "sanitized"
    assert validator.check(final)["ok"]


@needs_parser
def test_repair_loop_stubs_hopeless_source() -> None:
    src = "graph TD\n  ]][[ totally broken &&& --> ((("
    final, report = repair_diagram("component", src, validator=validator)
    assert report["status"] == "stubbed"
    assert report["needs_manual_review"] is True
    assert report["original_source"] == src
    assert validator.check(final)["ok"]


@needs_parser
def test_repair_loop_uses_model_before_sanitizer() -> None:
    class FakeRepairClient:
        def __init__(self) -> None:
            self.calls = 0

        def chat_structured(self, **kwargs) -> str:
            self.calls += 1
            return '{"mermaid": "graph TD\\n  a[\\"OAuth (Google)\\"] --> b[End]"}'

    client = FakeRepairClient()
    src = "graph TD\n  a[OAuth (Google)] --> b[End]"
    final, report = repair_diagram(
        "component", src, validator=validator, client=client, model="fake"
    )
    assert client.calls == 1
    assert report["status"] == "repaired"
    assert validator.check(final)["ok"]
