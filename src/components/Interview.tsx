/**
 * Interview-back loop (DOD 2.5): 2-4 system-specific questions, typed or
 * voice answers (voice reuses the main capture flow + transcription), and
 * answers are injected into Stage 2.
 */
import { createSignal, For, onMount, Show } from "solid-js";
import { getSettings } from "../lib/ipc";
import {
  startRecording,
  stopRecording,
  transcribe,
} from "../lib/ipc";
import { errorText, setAnswer, setError, startGeneration, state } from "../state";

export default function Interview() {
  const [recordingFor, setRecordingFor] = createSignal<number | null>(null);
  const [autoMode, setAutoMode] = createSignal(false);
  const questions = () => state.stage1?.interview_questions ?? [];

  onMount(async () => {
    try {
      const s = await getSettings();
      setAutoMode(s.interview_auto_mode);
      if (s.interview_auto_mode) void startGeneration();
    } catch {
      /* settings unavailable — show normal interview */
    }
  });

  async function toggleVoiceAnswer(index: number) {
    if (recordingFor() === index) {
      try {
        const rec = await stopRecording();
        setRecordingFor(null);
        const result = await transcribe({ audio_path: rec.path });
        setAnswer(index, (state.interviewAnswers[index] || "") + result.transcript);
      } catch (err) {
        setError(errorText(err));
        setRecordingFor(null);
      }
      return;
    }
    try {
      await startRecording();
      setRecordingFor(index);
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <section class="panel">
      <Show when={autoMode()}>
        <p class="hint">Interview auto-mode is on — skipping questions…</p>
      </Show>
      <Show when={!autoMode()}>
      <h2>A few questions before the architecture</h2>
      <p class="hint">
        Answer what you can — answers sharpen the design. Skipping is fine; gaps become
        open questions in the spec.
      </p>
      <For each={questions()}>
        {(q, i) => (
          <div class="question">
            <p class="q-text">{q.question}</p>
            <p class="q-why">why it matters: {q.why_it_matters}</p>
            <div class="row gap">
              <textarea
                rows={2}
                placeholder="Type an answer (optional)…"
                data-testid={`answer-${i()}`}
                value={state.interviewAnswers[i()] ?? ""}
                onInput={(e) => setAnswer(i(), e.currentTarget.value)}
              />
              <button
                type="button"
                classList={{ record: recordingFor() === i() }}
                title="Answer by voice"
                onClick={() => void toggleVoiceAnswer(i())}
              >
                {recordingFor() === i() ? "■ Stop" : "🎙"}
              </button>
            </div>
          </div>
        )}
      </For>
      <div class="row right gap">
        <button
          type="button"
          class="primary"
          data-testid="generate"
          disabled={state.busy || recordingFor() !== null}
          onClick={() => void startGeneration()}
        >
          Generate architecture →
        </button>
      </div>
      <Show when={state.busy}>
        <p class="hint">working…</p>
      </Show>
      </Show>
    </section>
  );
}
