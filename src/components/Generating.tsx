/**
 * Generation view: stage indicator (DOD 2.6 "visible stage indicator
 * updating between each") plus the live token stream.
 */
import { onCleanup, onMount } from "solid-js";
import { EVENTS, onEvent, type SidecarStreamPayload } from "../lib/ipc";
import { appendToken, state } from "../state";

const STAGES = [
  { n: 1, label: "Constraints" },
  { n: 2, label: "Architecture" },
  { n: 3, label: "Artifacts" },
];

export default function Generating() {
  const unlisteners: Array<() => void> = [];
  onMount(async () => {
    unlisteners.push(
      await onEvent<SidecarStreamPayload>(EVENTS.pipelineToken, (p) => {
        const text = (p.data as { text?: string }).text;
        if (text) appendToken(text);
      }),
    );
  });
  onCleanup(() => unlisteners.forEach((u) => u()));

  return (
    <section class="panel">
      <h2>Designing your architecture</h2>
      <div class="stage-indicator" data-testid="stage-indicator">
        {STAGES.map((s) => (
          <span
            classList={{
              stage: true,
              done: state.activeStage > s.n || state.step === "results",
              active: state.activeStage === s.n,
            }}
          >
            {state.activeStage > s.n ? "✓" : s.n} {s.label}
          </span>
        ))}
      </div>
      <pre class="token-stream" data-testid="token-stream">
        {state.tokenTail || "…"}
      </pre>
    </section>
  );
}
