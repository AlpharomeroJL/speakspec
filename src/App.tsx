/**
 * Speakspec main window: a linear wizard over the pipeline.
 * record -> transcribing -> transcript -> constraints -> interview ->
 * generating -> results. Sidecar health is surfaced persistently.
 */
import { createSignal, Match, onCleanup, onMount, Show, Switch } from "solid-js";
import { EVENTS, onEvent, type SidecarStatusPayload, type SidecarStreamPayload } from "./lib/ipc";
import { state } from "./state";
import Recorder from "./components/Recorder";
import TranscriptReview from "./components/TranscriptReview";
import ConstraintReview from "./components/ConstraintReview";
import Interview from "./components/Interview";
import Generating from "./components/Generating";
import Results from "./components/Results";
import Library from "./components/Library";
import Setup from "./components/Setup";
import { listModels } from "./lib/ipc";
import "./App.css";

function App() {
  const [sidecar, setSidecar] = createSignal<SidecarStatusPayload | null>(null);
  const [asrNote, setAsrNote] = createSignal("");
  const [showLibrary, setShowLibrary] = createSignal(false);
  const [needsSetup, setNeedsSetup] = createSignal<boolean | null>(null);
  const unlisteners: Array<() => void> = [];

  async function checkModels() {
    try {
      const models = await listModels();
      setNeedsSetup(models.models.length === 0);
    } catch {
      setNeedsSetup(true); // ollama unreachable or sidecar down -> setup guidance
    }
  }

  onMount(async () => {
    unlisteners.push(
      await onEvent<SidecarStatusPayload>(EVENTS.sidecarStatus, (p) => {
        setSidecar(p);
        if (p.status === "ready") void checkModels();
      }),
    );
    void checkModels();
    unlisteners.push(
      await onEvent<SidecarStreamPayload>(EVENTS.asrProgress, (p) => {
        const data = p.data as { state?: string; fraction?: number };
        if (data.state === "transcribing" && typeof data.fraction === "number") {
          setAsrNote(`transcribing ${(data.fraction * 100).toFixed(0)}%`);
        } else if (data.state === "loading-model") {
          setAsrNote("loading speech model…");
        } else if (data.state === "gpu-oom-fallback") {
          setAsrNote("GPU out of memory — continuing on CPU");
        }
      }),
    );
  });
  onCleanup(() => unlisteners.forEach((u) => u()));

  return (
    <main class="container">
      <header class="row gap">
        <h1>Speakspec</h1>
        <span class="tagline">voice → architecture → AGENTS.md</span>
        <span class="spacer" />
        <button type="button" data-testid="library-toggle" onClick={() => setShowLibrary(!showLibrary())}>
          Library
        </button>
        <Show when={sidecar() && sidecar()!.status !== "ready"}>
          <span class="sidecar-warning" title={sidecar()?.message ?? ""}>
            AI engine: {sidecar()?.status}
          </span>
        </Show>
      </header>

      <Show when={showLibrary()}>
        <Library onClose={() => setShowLibrary(false)} />
      </Show>

      <Show when={state.error}>
        <div class="errorbox" data-testid="error">
          {state.error}
        </div>
      </Show>

      <Switch>
        <Match when={state.step === "record" && needsSetup() === true}>
          <Setup onReady={() => setNeedsSetup(false)} />
        </Match>
        <Match when={state.step === "record"}>
          <Recorder />
        </Match>
        <Match when={state.step === "transcribing"}>
          <section class="panel">
            <h2>Transcribing…</h2>
            <p class="hint">{asrNote() || "loading speech model…"}</p>
          </section>
        </Match>
        <Match when={state.step === "transcript"}>
          <TranscriptReview />
        </Match>
        <Match when={state.step === "constraints"}>
          <ConstraintReview />
        </Match>
        <Match when={state.step === "interview"}>
          <Interview />
        </Match>
        <Match when={state.step === "generating"}>
          <Generating />
        </Match>
        <Match when={state.step === "results"}>
          <Results />
        </Match>
      </Switch>
    </main>
  );
}

export default App;
