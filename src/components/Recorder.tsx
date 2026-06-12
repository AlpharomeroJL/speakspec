/**
 * Recording screen: circular mic button, template preset chips, live level
 * meter, duration limits, file import via dialog or drag-and-drop.
 * Mirrors DOD 2.1.
 */
import { createSignal, For, onCleanup, onMount, Show } from "solid-js";
import { open } from "@tauri-apps/plugin-dialog";
import { getCurrentWebview } from "@tauri-apps/api/webview";
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
import {
  audioReady,
  errorText,
  setDurationMs,
  setError,
  setTemplate,
  state,
  TEMPLATES,
} from "../state";

export default function Recorder() {
  const [recState, setRecState] = createSignal<"idle" | "recording" | "paused">("idle");
  const [level, setLevel] = createSignal(0);
  const [elapsed, setElapsed] = createSignal(0);
  const [warning, setWarning] = createSignal("");
  const [dragOver, setDragOver] = createSignal(false);
  const unlisteners: Array<() => void> = [];
  let bars: HTMLDivElement | undefined;
  let activeSessionDir = "";
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
            (bars.children[i] as HTMLElement).style.height = `${4 + history[i] * 48}px`;
          }
        }
      }),
    );
    unlisteners.push(
      await onEvent<AudioStatePayload>(EVENTS.audioState, (p) => {
        if (p.state === "stopped") {
          const result = p.result as { path: string; duration_ms?: number } | undefined;
          const reason = p.reason as string | undefined;
          if (result?.path && reason && reason !== "user") {
            // Auto-stop (silence or hard limit) — proceed like a user stop.
            setRecState("idle");
            setDurationMs(result.duration_ms ?? null);
            void audioReady(result.path, activeSessionDir);
          }
        }
      }),
    );
    unlisteners.push(
      await onEvent<{ kind: string; elapsed_ms: number }>(EVENTS.audioWarning, () => {
        setWarning("25 minutes recorded — hard stop at 30:00.");
      }),
    );
    // Native file drag-and-drop from the OS.
    const webview = getCurrentWebview();
    const unlistenDrop = await webview.onDragDropEvent((event) => {
      if (event.payload.type === "over") setDragOver(true);
      if (event.payload.type === "leave") setDragOver(false);
      if (event.payload.type === "drop") {
        setDragOver(false);
        const path = event.payload.paths[0];
        if (path) void importPath(path);
      }
    });
    unlisteners.push(unlistenDrop);
  });
  onCleanup(() => unlisteners.forEach((u) => u()));

  async function importPath(path: string) {
    setError(null);
    try {
      const imported = await importAudio(path);
      await audioReady(imported.path, imported.session_dir);
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function onStart() {
    setError(null);
    try {
      const started = await startRecording();
      activeSessionDir = started.session_dir;
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
      setDurationMs(result.duration_ms);
      await audioReady(result.path, activeSessionDir);
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function onImportClick() {
    setError(null);
    const file = await open({
      multiple: false,
      filters: [{ name: "Audio", extensions: ["wav", "mp3", "m4a", "flac", "ogg", "webm"] }],
    });
    if (typeof file === "string") void importPath(file);
  }

  const mmss = () => {
    const s = Math.floor(elapsed() / 1000);
    return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  };

  return (
    <section class="panel">
      <div class="panel-pad">
        <Show
          when={recState() === "idle"}
          fallback={
            <div class="rec-hero" style="padding-top: 10px">
              <div class="meter" ref={bars} data-testid="level-meter">
                {Array.from({ length: 48 }).map(() => (
                  <span class="bar" />
                ))}
              </div>
              <div class="row center" style="margin-bottom: 12px">
                <span class="elapsed" data-testid="elapsed">
                  {mmss()}
                </span>
                <span classList={{ dot: true, live: recState() === "recording" }} />
              </div>
              <Show when={warning()}>
                <p class="warning">{warning()}</p>
              </Show>
              <div class="row center gap">
                <button type="button" onClick={() => void onPauseResume()}>
                  {recState() === "recording" ? "Pause" : "Resume"}
                </button>
                <button type="button" class="primary" onClick={() => void onStop()}>
                  Stop & transcribe
                </button>
              </div>
              <p class="level-debug">input level: {level().toFixed(3)}</p>
            </div>
          }
        >
          <div class="rec-hero">
            <button
              type="button"
              class="mic-btn"
              data-testid="record"
              title="Start recording"
              onClick={() => void onStart()}
            >
              ●
            </button>
            <div class="rec-tag">
              Talk through your idea — what it does, who uses it, what it talks to,
              <br />
              how fast it must ship. We handle the rest.
            </div>
          </div>
          <div class="row center gap wrap" style="margin: 16px 0 4px">
            <For each={[...TEMPLATES]}>
              {(t) => (
                <button
                  type="button"
                  classList={{ chip: true, select: true, violet: state.template === t }}
                  data-testid="template-chip"
                  onClick={() => setTemplate(t)}
                >
                  {t}
                </button>
              )}
            </For>
          </div>
          <div
            classList={{ dropzone: true, over: dragOver() }}
            data-testid="dropzone"
            onClick={() => void onImportClick()}
          >
            ⇪ drop an audio file — or click to browse (wav, mp3, m4a, flac, ogg, webm)
          </div>
        </Show>
      </div>
    </section>
  );
}
