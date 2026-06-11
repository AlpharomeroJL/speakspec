# Good First Issue drafts

To be filed as tagged issues when the repository goes public (release
checklist requires ≥3, at least one template-related).

## 1. Add a "Mobile app backend" template preset (template-related)

`templates/presets.json` ships five presets. Add a sixth for mobile-app
backends: pick an honest `optimize_for` (offline-first sync? push
notifications? app-store release cadence?) and a `default_language_tendency`
consistent with the PRD's language matrix. No code changes required — the
preset appears in the UI automatically. Acceptance: the new template produces
visibly different Stage 2 output from "API service" on the gym fixture
transcript (`sidecar/tests/run_template_check.py` extended to 6 templates).

## 2. Expand the tech-vocab dictionary with data-engineering terms

`dicts/tech-vocab.json` corrects ASR mishearings. Add ~15 entries for the
data world (dbt, DuckDB, Airflow, Parquet, Iceberg, Snowflake, ClickHouse…)
as misheard-form → canonical pairs. Constraint: keys must never occur in
ordinary English — `tests/test_vocab.py`'s clean-text corpus must stay green.

## 3. Add `subgraph` support to the component-diagram sanitizer

`sidecar/speakspec/mermaid_repair.py`'s `_convert_flowchart_dialect` converts
pseudo-flowchart dialects but passes `subgraph` blocks through untouched.
Small models sometimes emit unterminated subgraphs (missing `end`). Add a
deterministic balance check (open subgraphs get a closing `end`) plus a unit
test against the real parser in `tests/test_mermaid_repair.py`.

## 4. Surface diagram repair status in exports

`spec.md` embeds final diagram sources but not their repair provenance.
Append a one-line HTML comment per diagram (`<!-- speakspec: repaired -->`)
sourced from `diagram_reports`, so downstream tooling can flag
manually-reviewable diagrams. Touches `sidecar/speakspec/exports.py` and
`tests/test_exports.py`.
