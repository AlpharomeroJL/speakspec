# Speakspec Architecture: Process Topology and the Four IPC Contracts

Speakspec is four cooperating pieces. Everything else in the app is built
against these boundaries, so they are defined here first and changed only
deliberately.

```
┌────────────────┐  Contract A   ┌────────────────┐  Contract B   ┌────────────────┐
│   Solid.js     │ ───invoke──▶  │   Rust core    │ ──stdin────▶  │ Python sidecar │
│   (webview)    │ ◀──events───  │   (Tauri 2)    │ ◀─stdout────  │  (long-lived)  │
└────────────────┘               └────────────────┘               └───────┬────────┘
                                                                Contract C │ Contract D
                                                                 HTTP/SSE  │ in-process
                                                                     ▼     ▼
                                                              ┌─────────┐ ┌──────────────┐
                                                              │ Ollama  │ │faster-whisper│
                                                              │ :11434  │ │  (ASR)       │
                                                              └─────────┘ └──────────────┘
```

Privacy invariant across all boundaries: no audio, transcript, or spec bytes
leave the machine unless the user explicitly enables a cloud key in settings.
The only network traffic in the default configuration is `localhost:11434`.

---

## Contract A — Solid.js ↔ Rust (Tauri)

The frontend calls Rust through Tauri `#[command]`s and receives pushes
through Tauri events. The typed surface lives in
[`src/lib/ipc.ts`](../src/lib/ipc.ts) and must mirror
[`src-tauri/src/commands.rs`](../src-tauri/src/commands.rs) and the event
constants in [`src-tauri/src/sidecar/mod.rs`](../src-tauri/src/sidecar/mod.rs).

### Commands (grow as features land)

| Command | Args | Returns |
|---|---|---|
| `ping_sidecar` | `payload?: object` | `PingResult` |
| `cancel_sidecar_request` | `requestId: string` | cancellation ack |
| `frontend_log` | `message: string` | — (dev console print) |

Every command returns `Result<T, AppError>` where `AppError` is
`{ code: string, message: string }` — `message` is always human-readable.

### Events

| Event | Emitted when | Payload |
|---|---|---|
| `pipeline://stage-start` | a pipeline stage begins | `{ stage }` |
| `pipeline://token` | the model streams a token in any pipeline stage | `{ id, method, data: { text } }` |
| `pipeline://stage-done` | a stage's validated output is ready | `{ stage, result }` |
| `pipeline://error` | a stage failed after retries | `{ stage, code, message }` |
| `pipeline://progress` | non-token pipeline status | `{ id, method, data }` |
| `asr://progress` | transcription progress | `{ id, method, data }` |
| `sidecar://status` | sidecar lifecycle change | `{ status: ready\|failed\|crashed\|dead, message }` |
| `sidecar://progress` | progress for non-pipeline methods (e.g. `ping`) | `{ id, method, data }` |

---

## Contract B — Rust ↔ Python sidecar (NDJSON over stdio)

The sidecar is one long-running child process spawned by Rust. Transport is
newline-delimited JSON: one request line down, a stream of response lines
back. stdout is reserved exclusively for protocol lines; all sidecar logging
goes to stderr (surfaced in the dev console, never parsed).

### Envelope

Request (Rust → Python), one line:

```json
{"id": "r42", "method": "ping", "params": {}}
```

Responses (Python → Rust), each one line, all carrying the request `id`:

```json
{"id": "r42", "type": "progress", "data": {"note": "..."}}
{"id": "r42", "type": "token",    "data": {"text": "..."}}
{"id": "r42", "type": "result",   "data": {...}}
{"id": "r42", "type": "error",    "error": {"code": "...", "message": "...", "details": {}}}
```

Rules:

* Exactly one terminal line (`result` or `error`) per request. `token` and
  `progress` may repeat freely before it.
* Errors are structured and human-readable — never a raw traceback. Tracebacks
  go to stderr for diagnostics only.
* Requests run concurrently in the sidecar (worker threads), so a `ping`
  health check always answers even while ASR or a pipeline stage runs.
* `cancel` is a built-in method: `{"method": "cancel", "params": {"id": "r42"}}`
  sets a cancellation flag the running handler polls.
* Defined in code: Pydantic models in
  [`sidecar/speakspec/messages.py`](../sidecar/speakspec/messages.py), Rust
  structs in [`src-tauri/src/sidecar/protocol.rs`](../src-tauri/src/sidecar/protocol.rs).

### Lifecycle (owned entirely by Rust)

* **Spawn** on app start. Interpreter resolution order, no hardcoded paths:
  1. `SPEAKSPEC_SIDECAR_PYTHON` (+ `SPEAKSPEC_SIDECAR_DIR`) env override,
  2. dev layout `<repo>/sidecar/.venv` (debug builds),
  3. bundled layout `<resource_dir>/sidecar` (release builds).
* **Health check**: `ping` with a 15s timeout after every (re)spawn.
* **Restart on crash** with backoff (0.5s, 2s, 5s), then give up and emit
  `sidecar://status = dead`. Pending requests fail with `sidecar-crashed`.
* **Clean exit, no zombies**: on app exit Rust closes the child's stdin; the
  sidecar's read loop sees EOF and exits. After a grace period Rust kills any
  lingering process. The sidecar therefore cannot outlive the app even if
  Rust dies abruptly (EOF still fires).

### Stream routing (Rust side)

`token`/`progress` lines are forwarded as Contract A events based on the
originating method:

| Method prefix | `token` → | `progress` → |
|---|---|---|
| `pipeline*` | `pipeline://token` | `pipeline://progress` |
| `transcribe` | — | `asr://progress` |
| anything else | — | `sidecar://progress` |

---

## Contract C — Python ↔ Ollama (HTTP, localhost)

All LLM inference goes through the local Ollama server. Client:
`sidecar/speakspec/ollama_client.py` (httpx).

Non-negotiable request rules:

* `format` is always set to the active stage's JSON schema.
* `temperature` is always explicit (0 for Stages 1–2; Stage 3 prose may use 0.2).
* `num_ctx` is always explicit and sized to the input. The Ollama default of
  4096 silently truncates long transcripts; relying on it is a bug.
* Tokens stream (`"stream": true`) and are forwarded up as `token` lines.
* Installed models are detected at runtime via `GET /api/tags`. Model names
  are never hardcoded; the default comes from config with fallback to the
  best installed model.
* Base URL comes from config (default `http://localhost:11434`). If Ollama is
  unreachable, the sidecar returns the structured error
  `ollama-unavailable` with install guidance (https://ollama.com/download) —
  the build and the app never hard-fail on a missing Ollama.

## Contract D — Python ↔ faster-whisper (in-process)

ASR runs inside the sidecar process via the faster-whisper library.

* Model selection by hardware detection at runtime: CUDA GPU available →
  `large-v3-turbo`; CPU-only → `small.en`. Both overridable in config.
* Transcription streams `progress` lines (segment timestamps / fraction done)
  which surface as `asr://progress`.
* Model weights are downloaded at runtime to the local cache, never bundled
  with the app installer.

---

## Phase 2 end-to-end proof

`App.tsx` pings on startup: frontend `invoke("ping_sidecar")` → Rust writes
`{"method":"ping"}` to sidecar stdin → sidecar streams `progress` (forwarded
to the `sidecar://progress` event) then `result` → Rust resolves the invoke
promise → frontend renders both and echoes them through `frontend_log`, which
prints `FRONTEND RECEIVED …` in the dev console. One JSON message provably
survives every hop down and back.
