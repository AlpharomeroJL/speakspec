# ADR format (MADR)

Speakspec emits one Architecture Decision Record per `architecture_decision`
in the Stage 2 spec, in MADR (Markdown Any Decision Records) format — the
industry-standard shape for capturing a decision with its rationale.

## File layout

- Filename: `docs/adr/NNNN-decision-slug.md` (zero-padded, ordered to match
  the spec's decision order — enforced by the Stage 3 schema pattern).
- Sections, in order:

| Section | Content |
|---|---|
| **Status** | Always `Proposed` — Speakspec proposes; you accept by merging. |
| **Context** | The problem this decision addresses. |
| **Decision** | What was chosen. |
| **Confidence** | high / medium / low, carried from the Stage 2 schema, with the reason when not high. |
| **Consequences** | Positive and negative implications — both always present. |
| **Alternatives considered** | Every ruled-out option with its concrete rejection reason. |

## Reading confidence levels

- **high** — the constraint set clearly points to one answer with no
  significant tradeoff. Safe to act on.
- **medium** — reasonable, but it depends on at least one *inferred*
  constraint. Verify the inference before building on it.
- **low** — genuine ambiguity. The spec's open questions include a specific
  question whose answer resolves it — answer that first.

ADRs are deliberately discrete files so they are versionable and independently
shareable: commit them with the first PR and update Status as decisions are
accepted or superseded.
