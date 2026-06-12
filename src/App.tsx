/**
 * Speakspec main window: sidebar shell (new session / sessions / setup +
 * recent list) around the wizard flow:
 * record -> transcribing -> transcript -> constraints -> interview ->
 * generating -> results. Sidecar health and active model surface as badges.
 */
import {
  createEffect,
  createResource,
  createSignal,
  For,
  Match,
  onCleanup,
  onMount,
  Show,
  Switch,
} from "solid-js";
import {
  EVENTS,
  listModels,
  listSessions,
  loadSession,
  onEvent,
  type SessionSummary,
  type SidecarStatusPayload,
  type SidecarStreamPayload,
} from "./lib/ipc";
import { errorText, openStoredSession, resetSession, setError, setView, state } from "./state";
import Recorder from "./components/Recorder";
import TranscriptReview from "./components/TranscriptReview";
import ConstraintReview from "./components/ConstraintReview";
import Interview from "./components/Interview";
import Generating from "./components/Generating";
import Results from "./components/Results";
import Library from "./components/Library";
import Setup from "./components/Setup";
import Settings from "./components/Settings";
import "./App.css";

function App() {
  const [sidecar, setSidecar] = createSignal<SidecarStatusPayload | null>(null);
  const [asrNote, setAsrNote] = createSignal("");
  const [model, setModel] = createSignal<string | null>(null);
  const [needsSetup, setNeedsSetup] = createSignal<boolean | null>(null);
  const unlisteners: Array<() => void> = [];

  const [recent, { refetch: refetchRecent }] = createResource<SessionSummary[]>(
    () => listSessions().catch(() => []),
    { initialValue: [] },
  );

  async function checkModels() {
    try {
      const models = await listModels();
      setModel(models.selected);
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

  // Refresh the recent list whenever a run lands on the results screen.
  createEffect(() => {
    if (state.step === "results") void refetchRecent();
  });

  async function openRecent(id: string) {
    try {
      const stored = await loadSession(id);
      openStoredSession(stored.transcript, stored.spec_json, stored.dir);
    } catch (err) {
      setError(errorText(err));
    }
  }

  const age = (ms: number) => {
    const minutes = Math.max(1, Math.round((Date.now() - ms) / 60000));
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 48) return `${hours}h ago`;
    return `${Math.round(hours / 24)}d ago`;
  };

  return (
    <div class="shell">
      <aside class="sidebar">
        <div class="brand">
          <span class="brand-name">speakspec</span>
          <span class="badge-local">local</span>
        </div>
        <div class="ssec">workspace</div>
        <button
          type="button"
          classList={{ sitem: true, active: state.view === "wizard" && state.step === "record" }}
          onClick={() => resetSession()}
        >
          ● New session
        </button>
        <button
          type="button"
          classList={{ sitem: true, active: state.view === "library" }}
          data-testid="library-toggle"
          onClick={() => setView("library")}
        >
          ▤ Sessions
        </button>
        <button
          type="button"
          classList={{ sitem: true, active: state.view === "setup" }}
          onClick={() => setView("setup")}
        >
          ⚙ Setup & models
        </button>
        <button
          type="button"
          classList={{ sitem: true, active: state.view === "settings" }}
          onClick={() => setView("settings")}
        >
          ◈ Settings
        </button>
        <Show when={(recent() ?? []).length > 0}>
          <div class="ssec">recent</div>
          <For each={(recent() ?? []).slice(0, 5)}>
            {(session) => (
              <button type="button" class="ssess" onClick={() => void openRecent(session.id)}>
                <div class="stitle">{session.title || "(untitled)"}</div>
                <div class="smeta">{age(session.created_at)}</div>
              </button>
            )}
          </For>
        </Show>
        <span class="spacer" />
        <div style="padding: 0 14px">
          <Show when={model()}>
            <div class="mbadge" title="Active Ollama model">⌬ {model()}</div>
          </Show>
        </div>
      </aside>

      <main class="main">
        <div class="topbar">
          <span class="spacer" />
          <Show when={sidecar() && sidecar()!.status !== "ready"}>
            <span class="sidecar-warning" title={sidecar()?.message ?? ""}>
              AI engine: {sidecar()?.status}
            </span>
          </Show>
        </div>

        <Show when={state.error}>
          <div class="errorbox" data-testid="error">
            {state.error}
          </div>
        </Show>

        <Switch>
          <Match when={state.view === "library"}>
            <Library onClose={() => setView("wizard")} />
          </Match>
          <Match when={state.view === "setup"}>
            <Setup onReady={() => setView("wizard")} />
          </Match>
          <Match when={state.view === "settings"}>
            <Settings onClose={() => setView("wizard")} />
          </Match>
          <Match when={state.step === "record" && needsSetup() === true}>
            <Setup onReady={() => setNeedsSetup(false)} />
          </Match>
          <Match when={state.step === "record"}>
            <Recorder />
          </Match>
          <Match when={state.step === "transcribing"}>
            <section class="panel">
              <div class="panel-pad">
                <h2>Transcribing…</h2>
                <p class="hint">{asrNote() || "loading speech model…"}</p>
              </div>
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
    </div>
  );
}

export default App;
