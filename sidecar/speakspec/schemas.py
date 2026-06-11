"""Pydantic models mirroring the three locked pipeline schemas.

The canonical schemas are the JSON files in ``docs/schemas/`` — they are sent
verbatim to Ollama as the ``format`` constraint. These models are the runtime
validators for what comes back. Field names, enums, and length/count bounds
must stay in lockstep with the JSON files; ``tests/test_schemas.py`` checks
example objects against both representations.
"""

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Confidence = Literal["high", "medium", "low"]

CONSTRAINT_CATEGORIES = (
    "deployment_target",
    "team_size",
    "latency_requirement",
    "scale_expectation",
    "ops_complexity_budget",
    "ship_timeline",
    "external_integrations",
    "language_preference",
    "persistence_requirements",
    "security_posture",
    "quality_goals",
)

ConstraintCategory = Literal[
    "deployment_target",
    "team_size",
    "latency_requirement",
    "scale_expectation",
    "ops_complexity_budget",
    "ship_timeline",
    "external_integrations",
    "language_preference",
    "persistence_requirements",
    "security_posture",
    "quality_goals",
]


class _Strict(BaseModel):
    """Base with ``additionalProperties: false`` semantics."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# Stage 1 — constraint_extraction_v1.json
# --------------------------------------------------------------------------


class Analogy(_Strict):
    """A spoken comparison ('like X but for Y') and what it implies."""

    comparison: str
    implication: str


class Constraint(_Strict):
    """One tracked constraint with provenance and confidence."""

    category: ConstraintCategory
    value: str
    source: Literal["stated", "inferred"]
    confidence: Confidence


class InterviewQuestion(_Strict):
    """A system-specific clarifying question and the decision it unlocks."""

    question: str
    why_it_matters: str


class ConstraintExtraction(_Strict):
    """Stage 1 output: cleaned intent + structured constraint set."""

    intent_summary: str = Field(min_length=200)
    core_intent: str = Field(min_length=10)
    analogies: list[Analogy]
    named_components: list[str]
    constraints: list[Constraint]
    open_questions: list[str]
    interview_questions: list[InterviewQuestion] = Field(min_length=2, max_length=4)


# --------------------------------------------------------------------------
# Stage 2 — architecture_spec_v1.json
# --------------------------------------------------------------------------


class RecommendedLanguage(_Strict):
    """Language chosen on technical fit, or honored user override."""

    language: str
    confidence: Confidence
    rationale: str
    overridden_by_user: bool


class QualityGoal(_Strict):
    """An arc42-style quality goal traced to its driving constraint."""

    goal: str
    driver: str


class Consequences(_Strict):
    """Positive and negative consequences of a decision."""

    positive: list[str] = Field(min_length=1)
    negative: list[str] = Field(min_length=1)


class RuledOut(_Strict):
    """A rejected alternative with a concrete rejection reason."""

    option: str
    rejection_reason: str


class ArchitectureDecision(_Strict):
    """One significant decision; maps 1:1 to a generated ADR file."""

    title: str
    chosen_option: str
    confidence: Confidence
    rationale: str
    consequences: Consequences
    ruled_out: list[RuledOut] = Field(min_length=1)


class OssComponent(_Strict):
    """A mature OSS library to use instead of building."""

    name: str
    version: str
    purpose: str
    why_selected: str
    do_not_build: Literal[True]


class RiskFlag(_Strict):
    """A proactively flagged risk the user did not mention."""

    risk: str
    severity: Confidence
    mitigation: str


class Complexity(_Strict):
    """Overall build complexity and its drivers."""

    rating: Literal["S", "M", "L", "XL"]
    time_estimate: str
    key_drivers: list[str] = Field(min_length=1)


class ArchitectureSpec(_Strict):
    """Stage 2 output: the opinionated architecture specification."""

    system_overview: str = Field(min_length=40)
    recommended_language: RecommendedLanguage
    quality_goals: list[QualityGoal] = Field(min_length=1)
    architecture_decisions: list[ArchitectureDecision] = Field(min_length=1)
    oss_components: list[OssComponent]
    what_not_to_build: list[str] = Field(min_length=1)
    risk_flags: list[RiskFlag]
    open_questions: list[str]
    complexity: Complexity
    constraints: list[str]


# --------------------------------------------------------------------------
# Stage 3 — output_bundle_v1.json
# --------------------------------------------------------------------------


class Adr(_Strict):
    """One MADR-format ADR file."""

    filename: str = Field(pattern=r"^docs/adr/[0-9]{4}-[a-z0-9-]+\.md$")
    markdown: str


class Diagrams(_Strict):
    """Raw Mermaid 11 source for each required diagram type."""

    sequence: str
    er: str
    component: str
    c4_context: str
    c4_container: str


class FirstPr(_Strict):
    """Definition of the first skeleton-only PR."""

    title: str
    scope: str
    tasks: list[str] = Field(min_length=1)
    time_estimate: str
    out_of_scope: list[str]


class OutputBundle(_Strict):
    """Stage 3 output: every export artifact."""

    agents_md: str
    claude_md_shim: str
    adrs: list[Adr] = Field(min_length=1)
    diagrams: Diagrams
    file_tree: str
    first_pr: FirstPr


# --------------------------------------------------------------------------
# Canonical JSON schema access
# --------------------------------------------------------------------------

STAGE_SCHEMA_FILES = {
    1: "constraint_extraction_v1.json",
    2: "architecture_spec_v1.json",
    3: "output_bundle_v1.json",
}

STAGE_MODELS = {
    1: ConstraintExtraction,
    2: ArchitectureSpec,
    3: OutputBundle,
}


def schema_dir() -> Path:
    """Locate the canonical schema directory.

    ``SPEAKSPEC_SCHEMA_DIR`` (set by the Rust core in packaged builds) wins;
    otherwise fall back to the repo-layout path relative to this package.
    """
    env = os.environ.get("SPEAKSPEC_SCHEMA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "docs" / "schemas"


def load_stage_schema(stage: int) -> dict:
    """Load the locked JSON schema for ``stage`` (1, 2, or 3)."""
    path = schema_dir() / STAGE_SCHEMA_FILES[stage]
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)
