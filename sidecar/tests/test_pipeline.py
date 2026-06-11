"""Unit tests for the stage runner: prompts, num_ctx, retry, semantic gates.

These run with a fake Ollama client — no network, no model — so the
validation/retry plumbing is proven even on machines without Ollama.
"""

import json
from pathlib import Path

import pytest

from speakspec import prompts
from speakspec.messages import SidecarError
from speakspec.model_select import choose_model
from speakspec.pipeline import run_stage, semantic_check, size_num_ctx, stage1_message
from speakspec.schemas import ConstraintExtraction

FIXTURES = Path(__file__).parent / "fixtures"
STAGE1_EXAMPLE = json.loads(
    (FIXTURES / "examples" / "stage1_example.json").read_text(encoding="utf-8")
)


class FakeClient:
    """Returns scripted responses; records every call's kwargs."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat_structured(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return self.responses.pop(0)


def test_prompts_load_all_three_stages() -> None:
    for stage in (1, 2, 3):
        text = prompts.system_prompt(stage)
        assert "Speakspec" in text
    assert "{raw_transcript}" not in stage1_message("hi there", "")


def test_user_template_renders_placeholders() -> None:
    msg = stage1_message("RAW TEXT HERE", "ANSWER HERE")
    assert "RAW TEXT HERE" in msg
    assert "ANSWER HERE" in msg
    assert msg.index("TRANSCRIPT:") < msg.index("INTERVIEW ANSWERS")


def test_num_ctx_explicit_and_clamped() -> None:
    small = size_num_ctx(1, "sys", "short")
    assert small == 8192  # never below the floor, never the ollama default
    huge = size_num_ctx(3, "s" * 200_000, "u" * 200_000)
    assert huge == 32768  # clamped to the ceiling


def test_run_stage_retries_with_validation_error_appended() -> None:
    bad = json.dumps({"intent_summary": "too short"})
    good = json.dumps(STAGE1_EXAMPLE)
    client = FakeClient([bad, good])
    result = run_stage(1, "USER MSG", client=client, model="fake", ctx=None)
    assert isinstance(result, ConstraintExtraction)
    assert len(client.calls) == 2
    retry_msg = client.calls[1]["user"]
    assert "FAILED VALIDATION" in retry_msg
    assert "Fix only the invalid fields" in retry_msg


def test_run_stage_gives_up_after_three_retries() -> None:
    client = FakeClient(["not json"] * 4)
    with pytest.raises(SidecarError) as exc_info:
        run_stage(1, "USER MSG", client=client, model="fake", ctx=None)
    assert exc_info.value.code == "stage-validation-failed"
    assert exc_info.value.details["stage"] == 1
    assert len(client.calls) == 4  # initial + 3 retries


def test_semantic_gate_rejects_inferred_language_preference() -> None:
    example = json.loads(json.dumps(STAGE1_EXAMPLE))
    for constraint in example["constraints"]:
        if constraint["category"] == "language_preference":
            constraint["source"] = "inferred"
    parsed = ConstraintExtraction.model_validate(example)
    with pytest.raises(ValueError, match="language_preference"):
        semantic_check(1, parsed)


def test_run_stage_recovers_from_semantic_failure() -> None:
    inferred = json.loads(json.dumps(STAGE1_EXAMPLE))
    for constraint in inferred["constraints"]:
        if constraint["category"] == "language_preference":
            constraint["source"] = "inferred"
    client = FakeClient([json.dumps(inferred), json.dumps(STAGE1_EXAMPLE)])
    result = run_stage(1, "USER MSG", client=client, model="fake", ctx=None)
    assert isinstance(result, ConstraintExtraction)
    assert "language_preference" in client.calls[1]["user"]


def test_choose_model_prefers_config_then_tiers() -> None:
    installed = [
        {"name": "llama2:7b", "size": 4_000_000_000},
        {"name": "qwen3:8b", "size": 5_000_000_000},
    ]
    assert choose_model(installed, preferred="llama2") == "llama2:7b"
    assert choose_model(installed, preferred=None) == "qwen3:8b"
    with pytest.raises(SidecarError, match="No Ollama models"):
        choose_model([], None)
