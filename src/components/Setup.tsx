/**
 * First-run setup (DOD 2.14): hardware report, Ollama guidance, model
 * download with percent + ETA (resumable), manual override by picking any
 * tier's model.
 */
import { createResource, createSignal, For, onCleanup, onMount, Show } from "solid-js";
import { EVENTS, invokeRaw, onEvent, type SidecarStreamPayload } from "../lib/ipc";
import { errorText, setError } from "../state";

interface HardwareReport {
  asr: { device: string; model: string };
  vram_gb: number | null;
  ollama_reachable: boolean;
  installed_models: string[];
  selected_model: string | null;
  recommended_tier: string;
  tier_patterns: string[];
  install_hint: string | null;
}

export default function Setup(props: { onReady: () => void }) {
  const [report, { refetch }] = createResource<HardwareReport>(() =>
    invokeRaw<HardwareReport>("system_hardware"),
  );
  const [pulling, setPulling] = createSignal<string | null>(null);
  const [progress, setProgress] = createSignal<{ percent: number | null; status: string }>({
    percent: null,
    status: "",
  });
  const startedAt = { t: 0 };
  const unlisteners: Array<() => void> = [];

  onMount(async () => {
    unlisteners.push(
      await onEvent<SidecarStreamPayload>(EVENTS.sidecarProgress, (p) => {
        const data = p.data as { state?: string; percent?: number | null; status?: string };
        if (data.state === "pulling") {
          setProgress({ percent: data.percent ?? null, status: data.status ?? "" });
        }
      }),
    );
  });
  onCleanup(() => unlisteners.forEach((u) => u()));

  const eta = () => {
    const pct = progress().percent;
    if (!pct || pct <= 0 || !startedAt.t) return "";
    const elapsed = (Date.now() - startedAt.t) / 1000;
    const remaining = (elapsed / pct) * (100 - pct);
    return remaining > 90
      ? `~${Math.round(remaining / 60)} min left`
      : `~${Math.round(remaining)}s left`;
  };

  async function pull(name: string) {
    setPulling(name);
    startedAt.t = Date.now();
    try {
      await invokeRaw("pull_model", { name });
      await refetch();
      props.onReady();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setPulling(null);
    }
  }

  return (
    <section class="panel">
      <h2>First-run setup</h2>
      <Show when={report()} fallback={<p class="hint">detecting hardware…</p>}>
        <p class="hint" data-testid="hardware-report">
          Speech model: <strong>{report()!.asr.model}</strong> on {report()!.asr.device}
          {report()!.vram_gb ? ` · GPU VRAM: ${report()!.vram_gb} GB` : " · no NVIDIA GPU"}
          {" · recommended tier: "}
          <strong>{report()!.recommended_tier}</strong>
        </p>

        <Show when={!report()!.ollama_reachable}>
          <div class="errorbox">
            Ollama is not reachable. {report()!.install_hint}
            <div class="row gap" style="margin-top:0.5rem">
              <button type="button" onClick={() => void refetch()}>
                Check again
              </button>
            </div>
          </div>
        </Show>

        <Show when={report()!.ollama_reachable && report()!.installed_models.length === 0}>
          <p>No models installed yet. Pull one to get started (resumes if interrupted):</p>
          <div class="row gap wrap">
            <For each={report()!.tier_patterns}>
              {(name) => (
                <button
                  type="button"
                  class="primary"
                  disabled={pulling() !== null}
                  onClick={() => void pull(name)}
                >
                  {pulling() === name ? "Pulling…" : `Pull ${name}`}
                </button>
              )}
            </For>
          </div>
          <Show when={pulling()}>
            <p class="hint">
              {progress().status} {progress().percent != null ? `${progress().percent}%` : ""}{" "}
              {eta()}
            </p>
            <div class="pullbar">
              <div class="pullbar-fill" style={{ width: `${progress().percent ?? 0}%` }} />
            </div>
          </Show>
        </Show>

        <Show when={report()!.ollama_reachable && report()!.installed_models.length > 0}>
          <p>
            Ready — using <strong>{report()!.selected_model}</strong> (installed:{" "}
            {report()!.installed_models.join(", ")})
          </p>
          <button type="button" class="primary" onClick={() => props.onReady()}>
            Start →
          </button>
        </Show>
      </Show>
    </section>
  );
}
