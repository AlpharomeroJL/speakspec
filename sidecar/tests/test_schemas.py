"""Phase 3 gate: the locked JSON schemas and Pydantic mirrors agree.

For each stage: the schema file parses as valid Draft-07, a hand-written
example validates against the raw schema, and the same example validates
against the Pydantic model used at runtime.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from speakspec.schemas import STAGE_MODELS, load_stage_schema

EXAMPLES = Path(__file__).parent / "fixtures" / "examples"
EXAMPLE_FILES = {
    1: "stage1_example.json",
    2: "stage2_example.json",
    3: "stage3_example.json",
}


def _load_example(stage: int) -> dict:
    with (EXAMPLES / EXAMPLE_FILES[stage]).open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.parametrize("stage", [1, 2, 3])
def test_schema_is_valid_draft7(stage: int) -> None:
    schema = load_stage_schema(stage)
    Draft7Validator.check_schema(schema)


@pytest.mark.parametrize("stage", [1, 2, 3])
def test_example_validates_against_raw_schema(stage: int) -> None:
    schema = load_stage_schema(stage)
    example = _load_example(stage)
    errors = list(Draft7Validator(schema).iter_errors(example))
    assert not errors, "\n".join(e.message for e in errors)


@pytest.mark.parametrize("stage", [1, 2, 3])
def test_example_validates_against_pydantic_model(stage: int) -> None:
    model = STAGE_MODELS[stage]
    example = _load_example(stage)
    parsed = model.model_validate(example)
    # Round-trip: serializing back must not lose or rename fields.
    assert model.model_validate(json.loads(parsed.model_dump_json())) == parsed


def test_pydantic_rejects_extra_fields() -> None:
    example = _load_example(1)
    example["surprise"] = "x"
    with pytest.raises(Exception, match="surprise"):
        STAGE_MODELS[1].model_validate(example)


def test_pydantic_rejects_inferred_language_preference_shape() -> None:
    """The schema cannot express the no-inferred-language rule; the runner
    enforces it. This test pins the categories the rule keys on."""
    from speakspec.schemas import CONSTRAINT_CATEGORIES

    assert "language_preference" in CONSTRAINT_CATEGORIES
    assert len(CONSTRAINT_CATEGORIES) == 11
