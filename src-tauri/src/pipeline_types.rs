//! Rust mirror of the three locked pipeline schemas.
//!
//! Canonical sources are `docs/schemas/*.json` (sent to Ollama as `format`)
//! and the Pydantic models in `sidecar/speakspec/schemas.py` (runtime
//! validators). These structs exist so the Rust core can persist sessions,
//! render the constraint-review UI, and write export artifacts with
//! compile-time field checking. `deny_unknown_fields` mirrors
//! `additionalProperties: false`.

use serde::{Deserialize, Serialize};

/// Confidence level shared by several schema fields.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Confidence {
    /// Constraints clearly point to one answer.
    High,
    /// Reasonable but depends on an inferred constraint.
    Medium,
    /// Genuine ambiguity; must surface a resolving question.
    Low,
}

/// The eleven constraint categories Speakspec tracks.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ConstraintCategory {
    DeploymentTarget,
    TeamSize,
    LatencyRequirement,
    ScaleExpectation,
    OpsComplexityBudget,
    ShipTimeline,
    ExternalIntegrations,
    LanguagePreference,
    PersistenceRequirements,
    SecurityPosture,
    QualityGoals,
}

/// Whether a constraint was spoken or derived from context.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ConstraintSource {
    Stated,
    Inferred,
}

// ---------------------------------------------------------------------------
// Stage 1 — constraint_extraction_v1.json
// ---------------------------------------------------------------------------

/// A spoken comparison and its architectural implication.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Analogy {
    pub comparison: String,
    pub implication: String,
}

/// One tracked constraint with provenance and confidence.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Constraint {
    pub category: ConstraintCategory,
    pub value: String,
    pub source: ConstraintSource,
    pub confidence: Confidence,
}

/// A system-specific clarifying question for the interview-back step.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InterviewQuestion {
    pub question: String,
    pub why_it_matters: String,
}

/// Stage 1 output: cleaned intent + structured constraint set.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ConstraintExtraction {
    pub intent_summary: String,
    pub core_intent: String,
    pub analogies: Vec<Analogy>,
    pub named_components: Vec<String>,
    pub constraints: Vec<Constraint>,
    pub open_questions: Vec<String>,
    pub interview_questions: Vec<InterviewQuestion>,
}

// ---------------------------------------------------------------------------
// Stage 2 — architecture_spec_v1.json
// ---------------------------------------------------------------------------

/// Language chosen on technical fit, or honored user override.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RecommendedLanguage {
    pub language: String,
    pub confidence: Confidence,
    pub rationale: String,
    pub overridden_by_user: bool,
}

/// An arc42-style quality goal traced to its driving constraint.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct QualityGoal {
    pub goal: String,
    pub driver: String,
}

/// Positive and negative consequences of a decision.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Consequences {
    pub positive: Vec<String>,
    pub negative: Vec<String>,
}

/// A rejected alternative with its rejection reason.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RuledOut {
    pub option: String,
    pub rejection_reason: String,
}

/// One significant architecture decision; maps 1:1 to an ADR file.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArchitectureDecision {
    pub title: String,
    pub chosen_option: String,
    pub confidence: Confidence,
    pub rationale: String,
    pub consequences: Consequences,
    pub ruled_out: Vec<RuledOut>,
}

/// A mature OSS library to use instead of building.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OssComponent {
    pub name: String,
    pub version: String,
    pub purpose: String,
    pub why_selected: String,
    /// Always `true` per the schema (`const: true`).
    pub do_not_build: bool,
}

/// A proactively flagged risk the user did not mention.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RiskFlag {
    pub risk: String,
    pub severity: Confidence,
    pub mitigation: String,
}

/// Overall build complexity rating and drivers.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Complexity {
    pub rating: ComplexityRating,
    pub time_estimate: String,
    pub key_drivers: Vec<String>,
}

/// T-shirt complexity rating.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ComplexityRating {
    S,
    M,
    L,
    XL,
}

/// Stage 2 output: the opinionated architecture specification.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArchitectureSpec {
    pub system_overview: String,
    pub recommended_language: RecommendedLanguage,
    pub quality_goals: Vec<QualityGoal>,
    pub architecture_decisions: Vec<ArchitectureDecision>,
    pub oss_components: Vec<OssComponent>,
    pub what_not_to_build: Vec<String>,
    pub risk_flags: Vec<RiskFlag>,
    pub open_questions: Vec<String>,
    pub complexity: Complexity,
    pub constraints: Vec<String>,
}

// ---------------------------------------------------------------------------
// Stage 3 — output_bundle_v1.json
// ---------------------------------------------------------------------------

/// One MADR-format ADR file ready to write to disk.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Adr {
    pub filename: String,
    pub markdown: String,
}

/// Raw Mermaid 11 source for each required diagram.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Diagrams {
    pub sequence: String,
    pub er: String,
    pub component: String,
    pub c4_context: String,
    pub c4_container: String,
}

/// Definition of the first skeleton-only PR.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FirstPr {
    pub title: String,
    pub scope: String,
    pub tasks: Vec<String>,
    pub time_estimate: String,
    pub out_of_scope: Vec<String>,
}

/// Stage 3 output: every export artifact.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OutputBundle {
    pub agents_md: String,
    pub claude_md_shim: String,
    pub adrs: Vec<Adr>,
    pub diagrams: Diagrams,
    pub file_tree: String,
    pub first_pr: FirstPr,
}
