/**
 * Constraint review screen (DOD 2.4): all 11 categories rendered,
 * stated/inferred badges, inline editing that persists into Stage 2,
 * language-agnostic info box, template preset selection. Renders correctly
 * at 0, 4, or 11 detected constraints because every category always shows.
 */
import { For, Show } from "solid-js";
import {
  ALL_CATEGORIES,
  constraintsApproved,
  editConstraint,
  setTemplate,
  state,
} from "../state";

const TEMPLATES = ["Solo MVP", "API service", "CLI tool", "Browser extension", "Data pipeline"];

const LABELS: Record<string, string> = {
  deployment_target: "Deployment target",
  team_size: "Team size",
  latency_requirement: "Latency requirement",
  scale_expectation: "Scale expectation",
  ops_complexity_budget: "Ops complexity budget",
  ship_timeline: "Ship timeline",
  external_integrations: "External integrations",
  language_preference: "Language preference",
  persistence_requirements: "Persistence requirements",
  security_posture: "Security posture",
  quality_goals: "Quality goals",
};

export default function ConstraintReview() {
  const constraints = () => state.stage1?.constraints ?? [];
  const byCategory = (category: string) =>
    constraints()
      .map((c, i) => ({ c, i }))
      .filter(({ c }) => c.category === category);
  const languageStated = () =>
    byCategory("language_preference").some(
      ({ c }) => c.value.toLowerCase() !== "none stated" && c.value.trim() !== "",
    );

  return (
    <section class="panel wide">
      <h2>Review what was heard</h2>
      <Show when={state.busy}>
        <p class="hint">Extracting constraints…</p>
      </Show>
      <Show when={!state.busy && state.stage1}>
        <p class="hint">
          <strong>{state.stage1?.core_intent}</strong>
        </p>
        <p class="summary">{state.stage1?.intent_summary}</p>
        <Show when={!languageStated()}>
          <div class="infobox" data-testid="language-infobox">
            No language preference detected — the stack will be chosen on technical fit only.
            The AI handles the code.
          </div>
        </Show>
        <div class="constraint-grid" data-testid="constraint-grid">
          <For each={[...ALL_CATEGORIES]}>
            {(category) => (
              <div class="constraint-card">
                <h4>{LABELS[category]}</h4>
                <Show
                  when={byCategory(category).length > 0}
                  fallback={<p class="empty">not detected</p>}
                >
                  <For each={byCategory(category)}>
                    {({ c, i }) => (
                      <div class="constraint-row">
                        <input
                          value={c.value}
                          data-testid={`constraint-${category}`}
                          onInput={(e) => editConstraint(i, { value: e.currentTarget.value })}
                        />
                        <select
                          value={c.source}
                          onChange={(e) =>
                            editConstraint(i, {
                              source: e.currentTarget.value as "stated" | "inferred",
                            })
                          }
                        >
                          <option value="stated">stated</option>
                          <option value="inferred">inferred</option>
                        </select>
                        <span classList={{ badge: true, [c.confidence]: true }}>
                          {c.confidence}
                        </span>
                      </div>
                    )}
                  </For>
                </Show>
              </div>
            )}
          </For>
        </div>
        <div class="row gap wrap">
          <label>
            Template:
            <select
              value={state.template}
              data-testid="template-select"
              onChange={(e) => setTemplate(e.currentTarget.value)}
            >
              <For each={TEMPLATES}>{(t) => <option value={t}>{t}</option>}</For>
            </select>
          </label>
          <span class="spacer" />
          <button
            type="button"
            class="primary"
            data-testid="continue-to-interview"
            disabled={!state.constraintsReviewed}
            onClick={() => constraintsApproved()}
          >
            Looks right → clarifying questions
          </button>
        </div>
      </Show>
    </section>
  );
}
