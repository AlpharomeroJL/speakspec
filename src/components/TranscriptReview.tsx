/**
 * Editable transcript review. Edits persist through the entire pipeline
 * (DOD 2.2). Shows what the vocab pass corrected, with the raw original
 * recoverable.
 */
import { createSignal, Show } from "solid-js";
import { setTranscript, state, transcriptApproved } from "../state";

export default function TranscriptReview() {
  const [showRaw, setShowRaw] = createSignal(false);
  const result = () => state.transcriptResult;

  return (
    <section class="panel">
      <h2>Review the transcript</h2>
      <p class="hint">
        Fix anything the transcription got wrong — your edits are what the pipeline analyzes.
        {result()?.device === "cuda" ? " (GPU transcription)" : " (CPU transcription)"}
      </p>
      <Show when={(result()?.corrections.length ?? 0) > 0}>
        <details class="corrections">
          <summary>
            {result()?.corrections.length} technical term
            {result()!.corrections.length === 1 ? "" : "s"} auto-corrected
            <button type="button" class="link" onClick={() => setShowRaw(!showRaw())}>
              {showRaw() ? "show corrected" : "show raw"}
            </button>
          </summary>
          <ul>
            {result()?.corrections.map((c) => (
              <li>
                “{c.from.split("\\b").join("")}” → <strong>{c.to}</strong> ×{c.count}
              </li>
            ))}
          </ul>
        </details>
      </Show>
      <textarea
        rows={14}
        data-testid="transcript-editor"
        value={showRaw() ? (result()?.raw_transcript ?? "") : state.transcript}
        readonly={showRaw()}
        onInput={(e) => setTranscript(e.currentTarget.value)}
      />
      <div class="row right gap">
        <button
          type="button"
          class="primary"
          disabled={state.busy || state.transcript.trim().length === 0}
          onClick={() => void transcriptApproved()}
        >
          Extract constraints →
        </button>
      </div>
    </section>
  );
}
