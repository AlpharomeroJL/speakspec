/**
 * Contract A: typed surface between the Solid.js frontend and the Rust core.
 *
 * Commands go down via Tauri `invoke`; progress and streaming come back via
 * Tauri events. Event names and payload shapes mirror the Rust constants in
 * `src-tauri/src/sidecar/mod.rs` and `docs/architecture.md`.
 */
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

/** Tauri event channels pushed by the Rust core. */
export const EVENTS = {
  pipelineStageStart: "pipeline://stage-start",
  pipelineToken: "pipeline://token",
  pipelineStageDone: "pipeline://stage-done",
  pipelineError: "pipeline://error",
  pipelineProgress: "pipeline://progress",
  asrProgress: "asr://progress",
  sidecarStatus: "sidecar://status",
  sidecarProgress: "sidecar://progress",
  audioLevel: "audio://level",
  audioState: "audio://state",
  audioWarning: "audio://warning",
} as const;

export type EventName = (typeof EVENTS)[keyof typeof EVENTS];

/** Error shape every command rejects with (see `src-tauri/src/error.rs`). */
export interface AppError {
  code: string;
  message: string;
}

/** Payload for forwarded sidecar stream lines (token/progress events). */
export interface SidecarStreamPayload {
  id: string;
  method: string;
  data: Record<string, unknown>;
}

/** Payload for `sidecar://status` lifecycle events. */
export interface SidecarStatusPayload {
  status: "ready" | "failed" | "crashed" | "dead";
  message: string | null;
}

/** Result of the `ping` health check (see sidecar `handlers/ping.py`). */
export interface PingResult {
  pong: boolean;
  echo: Record<string, unknown>;
  sidecar_version: string;
  python: string;
}

/** Round-trip health check through Rust and the Python sidecar. */
export function pingSidecar(payload?: Record<string, unknown>): Promise<PingResult> {
  return invoke<PingResult>("ping_sidecar", { payload });
}

/** Cancel an in-flight sidecar request by its id. */
export function cancelSidecarRequest(requestId: string): Promise<unknown> {
  return invoke("cancel_sidecar_request", { requestId });
}

/** Print a line to the Rust dev console (used by automated e2e checks). */
export function frontendLog(message: string): Promise<void> {
  return invoke("frontend_log", { message });
}

/** Result wrapper returned by every pipeline stage handler. */
export interface StageResponse<T> {
  model: string;
  result: T;
}

/**
 * Run one pipeline stage. Stage params:
 * 1: `{ transcript, interview_answers?, model? }`
 * 2: `{ constraints, interview_answers?, template?, model? }`
 * 3: `{ architecture_spec, model? }`
 */
export function runPipelineStage<T>(
  stage: 1 | 2 | 3,
  params: Record<string, unknown>,
): Promise<StageResponse<T>> {
  return invoke<StageResponse<T>>("run_pipeline_stage", { stage, params });
}

/** Installed Ollama models plus the auto-selected default. */
export interface ModelsList {
  models: Array<{ name: string; size: number }>;
  selected: string | null;
}

/** List installed Ollama models (empty list if Ollama is unreachable). */
export function listModels(): Promise<ModelsList> {
  return invoke<ModelsList>("list_models");
}

// ---------------------------------------------------------------------------
// Audio capture + transcription (Phase 7)
// ---------------------------------------------------------------------------

/** `audio://level` payload, ~20 Hz while recording. */
export interface AudioLevelPayload {
  rms: number;
  peak: number;
  elapsed_ms: number;
  paused: boolean;
}

/** `audio://state` payload. */
export interface AudioStatePayload {
  state: "recording" | "paused" | "stopped" | "error";
  [key: string]: unknown;
}

/** Result of `stop_recording`. */
export interface RecordingResult {
  path: string;
  duration_ms: number;
  reason: "user" | "silence" | "hard-limit";
  sample_rate: number;
}

/** Start recording into a fresh session directory. */
export function startRecording(): Promise<{ path: string; session_dir: string }> {
  return invoke("start_recording");
}

/** Pause the active recording (file stays continuous). */
export function pauseRecording(): Promise<void> {
  return invoke("pause_recording");
}

/** Resume a paused recording. */
export function resumeRecording(): Promise<void> {
  return invoke("resume_recording");
}

/** Stop and finalize the recording. */
export function stopRecording(): Promise<RecordingResult> {
  return invoke<RecordingResult>("stop_recording");
}

/** Import an audio file; validates format with a per-format error. */
export function importAudio(
  sourcePath: string,
): Promise<{ path: string; session_dir: string; detected_format: string }> {
  return invoke("import_audio", { sourcePath });
}

/** Transcription result from the sidecar. */
export interface TranscribeResult {
  transcript: string;
  raw_transcript: string;
  corrections: Array<{ from: string; to: string; count: string }>;
  segments: Array<{ start: number; end: number; text: string }>;
  language: string;
  duration: number;
  device: string;
  model: string;
  fallback?: string;
}

/** Transcribe an audio file; progress streams via `asr://progress`. */
export function transcribe(params: {
  audio_path: string;
  model?: string;
  device?: string;
  language?: string;
}): Promise<TranscribeResult> {
  return invoke<TranscribeResult>("transcribe", { params });
}

/** Detected ASR hardware path (GPU/CPU and chosen model). */
export function asrHardware(): Promise<{
  device: string;
  model: string;
  compute_type: string;
  cuda_devices: number;
}> {
  return invoke("asr_hardware");
}

/** Write the full export bundle into the session directory. */
export function exportBundle(params: {
  session_dir: string;
  architecture_spec: Record<string, unknown>;
  output_bundle: Record<string, unknown>;
  diagram_reports?: Array<Record<string, unknown>>;
}): Promise<{ written: string[]; agents_gate: Record<string, unknown> }> {
  return invoke("export_bundle", { params });
}

/** Reveal a file in Windows Explorer. */
export function showInFolder(path: string): Promise<void> {
  return invoke("show_in_folder", { path });
}

// ---------------------------------------------------------------------------
// Session library (Phase 10)
// ---------------------------------------------------------------------------

/** One stored session, as listed in the library. */
export interface SessionSummary {
  id: string;
  created_at: number;
  title: string;
  dir: string;
  has_spec: boolean;
}

/** Persist a completed session. */
export function saveSession(args: {
  id: string;
  title: string;
  transcript: string;
  specJson: string;
  dir: string;
}): Promise<void> {
  return invoke("save_session", args);
}

/** All sessions, newest first. */
export function listSessions(): Promise<SessionSummary[]> {
  return invoke("list_sessions");
}

/** Full-text search over titles and transcripts. */
export function searchSessions(query: string): Promise<SessionSummary[]> {
  return invoke("search_sessions", { query });
}

/** Load a stored session for re-opening. */
export function loadSession(id: string): Promise<{
  transcript: string;
  spec_json: string;
  dir: string;
}> {
  return invoke("load_session", { id });
}

/** Delete a session and all of its files. */
export function deleteSession(id: string): Promise<void> {
  return invoke("delete_session", { id });
}

/** Subscribe to a typed Tauri event channel. Returns the unlisten handle. */
export function onEvent<T>(event: EventName, handler: (payload: T) => void): Promise<UnlistenFn> {
  return listen<T>(event, (e) => handler(e.payload));
}

/** Direct invoke escape hatch for commands without a dedicated wrapper. */
export function invokeRaw<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  return invoke<T>(command, args);
}

/** Persisted user settings (see `src-tauri/src/config.rs`). */
export interface AppSettings {
  default_model: string | null;
  asr_device: string;
  vram_override_gb: number | null;
  ollama_url: string;
  interview_auto_mode: boolean;
  cloud_stage3_enabled: boolean;
  cloud_provider: string;
  cloud_api_key: string | null;
  fast_pipeline: boolean;
}

export function getSettings(): Promise<AppSettings> {
  return invoke<AppSettings>("get_settings");
}

export function saveSettings(settings: AppSettings): Promise<void> {
  return invoke("save_settings", { settings });
}
