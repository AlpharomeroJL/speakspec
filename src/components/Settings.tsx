/**
 * Settings screen: hardware override, model picker, interview auto-mode,
 * optional cloud Stage 3, and advanced Ollama URL.
 */
import { createResource, createSignal, For, onMount, Show } from "solid-js";
import {
  getSettings,
  listModels,
  saveSettings,
  type AppSettings,
  type ModelsList,
} from "../lib/ipc";
import { errorText, setError } from "../state";

const DEFAULTS: AppSettings = {
  default_model: null,
  asr_device: "auto",
  vram_override_gb: null,
  ollama_url: "http://localhost:11434",
  interview_auto_mode: false,
  cloud_stage3_enabled: false,
  cloud_provider: "openai",
  cloud_api_key: null,
  fast_pipeline: false,
};

export default function Settings(props: { onClose: () => void }) {
  const [settings, setSettings] = createSignal<AppSettings>({ ...DEFAULTS });
  const [saving, setSaving] = createSignal(false);
  const [saved, setSaved] = createSignal(false);
  const [models] = createResource<ModelsList>(() => listModels().catch(() => ({ models: [], selected: null })));

  onMount(async () => {
    try {
      const loaded = await getSettings();
      setSettings({ ...DEFAULTS, ...loaded });
    } catch (err) {
      setError(errorText(err));
    }
  });

  function patch<K extends keyof AppSettings>(key: K, value: AppSettings[K]) {
    setSettings((s) => ({ ...s, [key]: value }));
    setSaved(false);
  }

  async function save() {
    setSaving(true);
    try {
      await saveSettings(settings());
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section class="panel">
      <div class="row gap" style="justify-content:space-between;align-items:center">
        <h2>Settings</h2>
        <button type="button" onClick={props.onClose}>
          Back
        </button>
      </div>

      <h3>Hardware</h3>
      <p class="hint">Override auto-detection when the reported device is wrong.</p>
      <label class="field">
        ASR device
        <select
          value={settings().asr_device}
          onChange={(e) => patch("asr_device", e.currentTarget.value)}
        >
          <option value="auto">Auto (GPU if available)</option>
          <option value="cuda">Force GPU</option>
          <option value="cpu">Force CPU</option>
        </select>
      </label>
      <label class="field">
        VRAM override (GB, optional)
        <input
          type="number"
          min="0"
          step="0.5"
          placeholder="e.g. 8"
          value={settings().vram_override_gb ?? ""}
          onInput={(e) => {
            const v = e.currentTarget.value;
            patch("vram_override_gb", v === "" ? null : Number(v));
          }}
        />
      </label>

      <h3>Models</h3>
      <label class="field">
        Default Ollama model
        <select
          value={settings().default_model ?? ""}
          onChange={(e) => patch("default_model", e.currentTarget.value || null)}
        >
          <option value="">Auto (best installed for hardware)</option>
          <For each={models()?.models ?? []}>
            {(m) => <option value={m.name}>{m.name}</option>}
          </For>
        </select>
      </label>
      <label class="field row gap">
        <input
          type="checkbox"
          checked={settings().fast_pipeline}
          onChange={(e) => patch("fast_pipeline", e.currentTarget.checked)}
        />
        Fast pipeline (use smaller models for Stage 1, Stage 3, and diagram repairs)
      </label>

      <h3>Interview</h3>
      <label class="field row gap">
        <input
          type="checkbox"
          checked={settings().interview_auto_mode}
          onChange={(e) => patch("interview_auto_mode", e.currentTarget.checked)}
        />
        Auto-mode: skip interview questions (leave answers blank)
      </label>

      <h3>Cloud Stage 3 (optional)</h3>
      <p class="hint">
        Off by default. When enabled, only the architecture spec text is sent to your
        provider — never audio. Diagram repair stays local.
      </p>
      <label class="field row gap">
        <input
          type="checkbox"
          checked={settings().cloud_stage3_enabled}
          onChange={(e) => patch("cloud_stage3_enabled", e.currentTarget.checked)}
        />
        Use cloud model for Stage 3 output generation
      </label>
      <Show when={settings().cloud_stage3_enabled}>
        <label class="field">
          Provider
          <select
            value={settings().cloud_provider}
            onChange={(e) => patch("cloud_provider", e.currentTarget.value)}
          >
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </label>
        <label class="field">
          API key
          <input
            type="password"
            placeholder="sk-…"
            value={settings().cloud_api_key ?? ""}
            onInput={(e) => patch("cloud_api_key", e.currentTarget.value || null)}
          />
        </label>
      </Show>

      <h3>Advanced</h3>
      <label class="field">
        Ollama URL
        <input
          type="url"
          value={settings().ollama_url}
          onInput={(e) => patch("ollama_url", e.currentTarget.value)}
        />
      </label>

      <div class="row gap" style="margin-top:1rem">
        <button type="button" class="primary" disabled={saving()} onClick={() => void save()}>
          {saving() ? "Saving…" : "Save settings"}
        </button>
        <Show when={saved()}>
          <span class="hint">Saved — AI engine restarted.</span>
        </Show>
      </div>
    </section>
  );
}
