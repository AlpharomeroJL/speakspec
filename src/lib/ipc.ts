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

/** Subscribe to a typed Tauri event channel. Returns the unlisten handle. */
export function onEvent<T>(event: EventName, handler: (payload: T) => void): Promise<UnlistenFn> {
  return listen<T>(event, (e) => handler(e.payload));
}
