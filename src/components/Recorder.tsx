/**
 * Recording screen: start/pause/resume/stop, live level meter, duration
 * limits surfaced, and file import. Mirrors DOD 2.1.
 */
import { createSignal, onCleanup, onMount, Show } from "solid-js";
import { open } from "@tauri-apps/plugin-dialog";
import {
  EVENTS,
  importAudio,
  onEvent,
  pauseRecording,
  resumeRecording,
  startRecording,
  stopRecording,
  type AudioLevelPayload,
  type AudioStatePayload,
} from "../lib/ipc";
import { audioReady, errorText, setError, state } from "../state";

export default function Recorder() {
  const [recState, setRecState] = createSignal<"idle" | "recording" | "paused">("idle");
  const [level, setLevel] = createSignal(0);
  const [elapsed, setElapsed] = createSignal(0);
  const [warning, setWarning] = createSignal("");
  const unlisteners: Array<() => void> = [];
  let bars: HTMLDivElement | undefined;
  const history: number[] = Array.from({ length: 48 }, () => 0);

  onMount(async () => {
    unlisteners.push(
      await onEvent<AudioLevelPayload>(EVENTS.audioLevel, (p) => {
        setLevel(p.rms);
        setElapsed(p.elapsed_ms);
        history.push(Math.min(1, p.rms * 6));
        history.shift();
        if (bars) {
          for (let i = 0; i < bars.children.length; i++) {
            (bars.children[i] as HTMLElement).style.height = `${4 + history[i] * 56}px`;
          }
        }
      }),
    );
    unlisteners.push(
      await onEvent<AudioStatePayload>(EVENTS.audioState, (p) => {
        if (p.state === "stopped") {
          const result = p.result as { path: string } | undefined;
          const reason = p.reason as string | undefined;
          if (result?.path && reason && reason !== "user") {
            // Auto-stop (silence or hard limit) — proceed like a user stop.
            setRecState("idle");
            void audioReady(result.path, state.sessionDir ?? "");
          }
        }
      }),
    );
    unlisteners.push(
      await onEvent<{ kind: string; elapsed_ms: number }>(EVENTS.audioWarning, () => {
        setWarning("25 minutes recorded — hard stop at 30:00.");
      }),
    );
  });
  onCleanup(() => unlisteners.forEach((u) => u()));

  async function onStart() {
    setError(null);
    try {
      await startRecording();
      setRecState("recording");
      setWarning("");
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function onPauseResume() {
    try {
      if (recState() === "recording") {
        await pauseRecording();
        setRecState("paused");
      } else {
        await resumeRecording();
        setRecState("recording");
      }
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function onStop() {
    try {
      const result = await stopRecording();
      setRecState("idle");
      await audioReady(result.path, state.sessionDir ?? "");
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function onImport() {
    setError(null);
    const file = await open({
      multiple: false,
      filters: [{ name: "Audio", extensions: ["wav", "mp3", "m4a", "flac", "ogg", "webm"] }],
    });
    if (typeof file !== "string") return;
    try {
      const imported = await importAudio(file);
      await audioReady(imported.path, imported.session_dir);
    } catch (err) {
      setError(errorText(err));
    }
  }

  const mmss = () => {
    const s = Math.floor(elapsed() / 1000);
    return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  };

  return (
    <section class="panel">
      <h2>Describe your system</h2>
      <p class="hint">
        Speak for ~90 seconds: what it does, who uses it, what it talks to, how fast it must
        ship. Recording stops automatically after a long silence, warns at 25:00, stops at 30:00.
      </p>
      <div class="meter" ref={bars} data-testid="level-meter">
        {Array.from({ length: 48 }).map(() => (
          <span class="bar" />
        ))}
      </div>
      <div class="row center">
        <span class="elapsed" data-testid="elapsed">
          {mmss()}
        </span>
        <span classList={{ dot: true, live: recState() === "recording" }} />
      </div>
      <Show when={warning()}>
        <p class="warning">{warning()}</p>
      </Show>
      <div class="row center gap">
        <Show
          when={recState() === "idle"}
          fallback={
            <>
              <button type="button" onClick={() => void onPauseResume()}>
                {recState() === "recording" ? "Pause" : "Resume"}
              </button>
              <button type="button" class="primary" onClick={() => void onStop()}>
                Stop & transcribe
              </button>
            </>
          }
        >
          <button type="button" class="primary record" data-testid="record" onClick={() => void onStart()}>
            ● Record
          </button>
          <button type="button" onClick={() => void onImport()}>
            Import audio…
          </button>
        </Show>
      </div>
      <p class="level-debug">input level: {level().toFixed(3)}</p>
    </section>
  );
}
