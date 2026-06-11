//! Sidecar process manager: owns the Python child's full lifecycle.
//!
//! Responsibilities (Contract B in `docs/architecture.md`):
//! * spawn the sidecar on app start and locate its interpreter without any
//!   hardcoded machine paths (env override -> dev layout -> bundled layout),
//! * health-check it with `ping`, restart it with backoff if it crashes,
//! * route streamed `token`/`progress` lines to Tauri events and terminal
//!   `result`/`error` lines back to the awaiting caller,
//! * close stdin on shutdown so the child exits (it reads to EOF), then kill
//!   it if it lingers — no zombie processes.

pub mod protocol;

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::sync::{mpsc, oneshot, Mutex, Notify};

use crate::error::AppError;
use protocol::{SidecarErrorBody, SidecarMsg, SidecarRequest};

/// Tauri event names pushed to the frontend (Contract A).
pub mod events {
    /// A pipeline stage began. Payload: `{ stage }`.
    pub const PIPELINE_STAGE_START: &str = "pipeline://stage-start";
    /// A streamed model token. Payload: `{ id, method, data: { text } }`.
    pub const PIPELINE_TOKEN: &str = "pipeline://token";
    /// A pipeline stage finished. Payload: `{ stage, result }`.
    pub const PIPELINE_STAGE_DONE: &str = "pipeline://stage-done";
    /// The pipeline failed. Payload: `{ stage, code, message }`.
    pub const PIPELINE_ERROR: &str = "pipeline://error";
    /// Non-terminal pipeline progress. Payload: `{ id, method, data }`.
    pub const PIPELINE_PROGRESS: &str = "pipeline://progress";
    /// ASR progress. Payload: `{ id, method, data }`.
    pub const ASR_PROGRESS: &str = "asr://progress";
    /// Sidecar lifecycle status. Payload: `{ status, message? }`.
    pub const SIDECAR_STATUS: &str = "sidecar://status";
    /// Generic sidecar progress for non-pipeline methods (e.g. `ping`).
    pub const SIDECAR_PROGRESS: &str = "sidecar://progress";
}

/// How long a `ping` health check may take before the spawn is failed.
const HEALTH_CHECK_TIMEOUT: Duration = Duration::from_secs(15);
/// Grace period between closing stdin and force-killing on shutdown.
const SHUTDOWN_GRACE: Duration = Duration::from_millis(800);
/// Respawn delays after successive crashes; after the last, give up.
const RESTART_BACKOFF: [Duration; 3] = [
    Duration::from_millis(500),
    Duration::from_secs(2),
    Duration::from_secs(5),
];

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

struct Pending {
    method: String,
    result_tx: oneshot::Sender<Result<Value, SidecarErrorBody>>,
}

struct Inner {
    app: AppHandle,
    stdin_tx: Mutex<Option<mpsc::UnboundedSender<String>>>,
    pending: Mutex<HashMap<String, Pending>>,
    next_id: AtomicU64,
    shutting_down: AtomicBool,
    kill_notify: Notify,
    crash_count: AtomicU64,
}

/// Cloneable handle to the managed sidecar process.
#[derive(Clone)]
pub struct SidecarManager {
    inner: Arc<Inner>,
}

impl SidecarManager {
    /// Create a manager bound to the app. Does not spawn yet; call `start`.
    pub fn new(app: AppHandle) -> Self {
        Self {
            inner: Arc::new(Inner {
                app,
                stdin_tx: Mutex::new(None),
                pending: Mutex::new(HashMap::new()),
                next_id: AtomicU64::new(1),
                shutting_down: AtomicBool::new(false),
                kill_notify: Notify::new(),
                crash_count: AtomicU64::new(0),
            }),
        }
    }

    /// Spawn the sidecar and run a `ping` health check.
    ///
    /// On failure, emits a `sidecar://status` event with a human-readable
    /// message instead of crashing the app — the UI shows setup guidance.
    pub async fn start(&self) {
        match self.spawn_and_health_check().await {
            Ok(version) => {
                self.inner.crash_count.store(0, Ordering::SeqCst);
                self.emit_status("ready", Some(format!("sidecar v{version} online")));
            }
            Err(err) => {
                self.emit_status("failed", Some(format!("{err:#}")));
            }
        }
    }

    /// Send `method` with `params`; await the terminal result.
    ///
    /// Streamed `token`/`progress` lines are forwarded as Tauri events while
    /// this future is pending. Fails fast if the sidecar is not running.
    pub async fn request(&self, method: &str, params: Value) -> Result<Value, AppError> {
        let id = format!("r{}", self.inner.next_id.fetch_add(1, Ordering::SeqCst));
        let line = serde_json::to_string(&SidecarRequest {
            id: id.clone(),
            method: method.to_string(),
            params,
        })
        .map_err(|e| AppError::new("internal", format!("could not encode request: {e}")))?;

        let (tx, rx) = oneshot::channel();
        self.inner.pending.lock().await.insert(
            id.clone(),
            Pending {
                method: method.to_string(),
                result_tx: tx,
            },
        );

        let send_ok = {
            let guard = self.inner.stdin_tx.lock().await;
            match guard.as_ref() {
                Some(tx) => tx.send(line).is_ok(),
                None => false,
            }
        };
        if !send_ok {
            self.inner.pending.lock().await.remove(&id);
            return Err(AppError::new(
                "sidecar-unavailable",
                "The AI sidecar process is not running. Check sidecar://status for setup guidance.",
            ));
        }

        match rx.await {
            Ok(Ok(value)) => Ok(value),
            Ok(Err(body)) => Err(AppError::new(body.code, body.message)),
            Err(_) => Err(AppError::new(
                "sidecar-crashed",
                "The AI sidecar stopped while processing this request. It is being restarted.",
            )),
        }
    }

    /// Ask the sidecar to cancel an in-flight request by id.
    pub async fn cancel(&self, request_id: &str) -> Result<Value, AppError> {
        self.request("cancel", json!({ "id": request_id })).await
    }

    /// Close stdin (EOF makes the child exit), then kill it after a grace
    /// period. Called once on app exit.
    pub async fn shutdown(&self) {
        self.inner.shutting_down.store(true, Ordering::SeqCst);
        self.inner.stdin_tx.lock().await.take(); // writer task ends -> stdin closes -> EOF
        tokio::time::sleep(SHUTDOWN_GRACE).await;
        self.inner.kill_notify.notify_waiters();
    }

    async fn spawn_and_health_check(&self) -> Result<String> {
        let (python, workdir) = resolve_sidecar_paths(&self.inner.app)?;
        self.spawn_child(&python, &workdir).await?;
        let pong = tokio::time::timeout(HEALTH_CHECK_TIMEOUT, self.request("ping", json!({})))
            .await
            .map_err(|_| anyhow!("sidecar did not answer the ping health check within 15s"))?
            .map_err(|e| anyhow!("sidecar health check failed: {e}"))?;
        Ok(pong
            .get("sidecar_version")
            .and_then(Value::as_str)
            .unwrap_or("unknown")
            .to_string())
    }

    async fn spawn_child(&self, python: &PathBuf, workdir: &PathBuf) -> Result<()> {
        let mut cmd = tokio::process::Command::new(python);
        cmd.arg("-m")
            .arg("speakspec")
            .current_dir(workdir)
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .kill_on_drop(true);
        #[cfg(windows)]
        {
            cmd.creation_flags(CREATE_NO_WINDOW);
        }
        let mut child = cmd
            .spawn()
            .with_context(|| format!("could not start sidecar python at {}", python.display()))?;

        let stdin = child
            .stdin
            .take()
            .context("sidecar child has no stdin pipe")?;
        let stdout = child
            .stdout
            .take()
            .context("sidecar child has no stdout pipe")?;
        let stderr = child
            .stderr
            .take()
            .context("sidecar child has no stderr pipe")?;

        // Writer task: serializes all request lines onto the child's stdin.
        let (tx, mut rx) = mpsc::unbounded_channel::<String>();
        *self.inner.stdin_tx.lock().await = Some(tx);
        tauri::async_runtime::spawn(async move {
            let mut stdin = stdin;
            while let Some(line) = rx.recv().await {
                if stdin.write_all(line.as_bytes()).await.is_err() {
                    break;
                }
                if stdin.write_all(b"\n").await.is_err() {
                    break;
                }
                if stdin.flush().await.is_err() {
                    break;
                }
            }
            // Channel closed: drop stdin so the child sees EOF and exits.
        });

        // Reader task: routes every stdout line to events or pending callers.
        let inner = Arc::clone(&self.inner);
        tauri::async_runtime::spawn(async move {
            let mut lines = BufReader::new(stdout).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                match serde_json::from_str::<SidecarMsg>(&line) {
                    Ok(msg) => route_message(&inner, msg).await,
                    Err(err) => eprintln!("[sidecar] unparseable stdout line ({err}): {line}"),
                }
            }
        });

        // Stderr task: sidecar logs are surfaced in the dev console only.
        tauri::async_runtime::spawn(async move {
            let mut lines = BufReader::new(stderr).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                eprintln!("[sidecar] {line}");
            }
        });

        // Waiter task: observes exit, fails pending requests, respawns.
        let manager = self.clone();
        tauri::async_runtime::spawn(async move {
            let status = tokio::select! {
                status = child.wait() => status.ok(),
                _ = manager.inner.kill_notify.notified() => {
                    let _ = child.start_kill();
                    child.wait().await.ok()
                }
            };
            manager.on_child_exit(status).await;
        });

        Ok(())
    }

    async fn on_child_exit(&self, status: Option<std::process::ExitStatus>) {
        // Fail every pending request with a structured error.
        let pending: Vec<Pending> = {
            let mut map = self.inner.pending.lock().await;
            map.drain().map(|(_, p)| p).collect()
        };
        for p in pending {
            let _ = p.result_tx.send(Err(SidecarErrorBody {
                code: "sidecar-crashed".into(),
                message: "The AI sidecar stopped before finishing this request.".into(),
                details: Value::Null,
            }));
        }
        self.inner.stdin_tx.lock().await.take();

        if self.inner.shutting_down.load(Ordering::SeqCst) {
            return;
        }

        let crash_n = self.inner.crash_count.fetch_add(1, Ordering::SeqCst) as usize;
        let code = status.map(|s| s.code().unwrap_or(-1)).unwrap_or(-1);
        self.emit_status(
            "crashed",
            Some(format!("sidecar exited with code {code}; restarting")),
        );
        match RESTART_BACKOFF.get(crash_n) {
            Some(delay) => {
                tokio::time::sleep(*delay).await;
                self.start_boxed().await;
            }
            None => {
                self.emit_status(
                    "dead",
                    Some(
                        "The AI sidecar crashed repeatedly and will not be restarted. \
                         Restart Speakspec to try again."
                            .to_string(),
                    ),
                );
            }
        }
    }

    /// Indirection so the recursive restart future stays boxed and `Send`.
    fn start_boxed(&self) -> std::pin::Pin<Box<dyn std::future::Future<Output = ()> + Send>> {
        let this = self.clone();
        Box::pin(async move { this.start().await })
    }

    fn emit_status(&self, status: &str, message: Option<String>) {
        let payload = json!({ "status": status, "message": message });
        if let Err(err) = self.inner.app.emit(events::SIDECAR_STATUS, payload) {
            eprintln!("[sidecar] could not emit status event: {err}");
        }
        if let Some(msg) = &message {
            eprintln!("[sidecar] status={status}: {msg}");
        }
    }
}

/// Route one sidecar stdout line: stream kinds become Tauri events, terminal
/// kinds resolve the awaiting `request` future.
async fn route_message(inner: &Arc<Inner>, msg: SidecarMsg) {
    match msg {
        SidecarMsg::Token { id, data } => stream_to_event(inner, id, data, true).await,
        SidecarMsg::Progress { id, data } => stream_to_event(inner, id, data, false).await,
        SidecarMsg::Result { id, data } => {
            if let Some(p) = inner.pending.lock().await.remove(&id) {
                let _ = p.result_tx.send(Ok(data));
            }
        }
        SidecarMsg::Error { id, error } => {
            if let Some(p) = inner.pending.lock().await.remove(&id) {
                let _ = p.result_tx.send(Err(error));
            }
        }
    }
}

/// Forward a streamed `token`/`progress` line to the Tauri event matching the
/// request's method (see the routing table in `docs/architecture.md`).
async fn stream_to_event(inner: &Arc<Inner>, id: String, data: Value, is_token: bool) {
    let method = {
        let map = inner.pending.lock().await;
        map.get(&id).map(|p| p.method.clone())
    };
    let Some(method) = method else { return };
    let event = if method.starts_with("pipeline") {
        if is_token {
            events::PIPELINE_TOKEN
        } else {
            events::PIPELINE_PROGRESS
        }
    } else if method == "transcribe" {
        events::ASR_PROGRESS
    } else {
        events::SIDECAR_PROGRESS
    };
    let payload = json!({ "id": id, "method": method, "data": data });
    if let Err(err) = inner.app.emit(event, payload) {
        eprintln!("[sidecar] could not emit {event}: {err}");
    }
}

/// Locate the sidecar interpreter and working directory. Resolution order:
///
/// 1. `SPEAKSPEC_SIDECAR_PYTHON` (+ optional `SPEAKSPEC_SIDECAR_DIR`) env vars,
/// 2. dev layout: `<repo>/sidecar/.venv` next to `src-tauri` (debug builds),
/// 3. bundled layout: `<resource_dir>/sidecar` (release builds, Phase 10).
fn resolve_sidecar_paths(app: &AppHandle) -> Result<(PathBuf, PathBuf)> {
    let mut tried: Vec<String> = Vec::new();

    if let Ok(python) = std::env::var("SPEAKSPEC_SIDECAR_PYTHON") {
        let python = PathBuf::from(python);
        let workdir = std::env::var("SPEAKSPEC_SIDECAR_DIR")
            .map(PathBuf::from)
            .ok()
            .or_else(|| default_workdir_for(&python))
            .context("SPEAKSPEC_SIDECAR_PYTHON is set but the sidecar directory could not be derived; set SPEAKSPEC_SIDECAR_DIR too")?;
        if python.exists() {
            return Ok((python, workdir));
        }
        tried.push(format!("env override: {}", python.display()));
    }

    #[cfg(debug_assertions)]
    {
        // Compile-time path of this crate; valid for dev runs on the machine
        // that built the binary, which is exactly the dev scenario.
        let repo_sidecar = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../sidecar");
        let python = repo_sidecar.join(venv_python_rel());
        if python.exists() {
            return Ok((python, repo_sidecar));
        }
        tried.push(format!("dev layout: {}", python.display()));
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        let bundled = resource_dir.join("sidecar");
        let python = bundled.join(venv_python_rel());
        if python.exists() {
            return Ok((python, bundled));
        }
        tried.push(format!("bundled layout: {}", python.display()));
    }

    Err(anyhow!(
        "No Python sidecar found. Tried: {}. \
         Run the first-run setup, or set SPEAKSPEC_SIDECAR_PYTHON to a Python 3.11+ \
         interpreter that has the speakspec sidecar installed.",
        tried.join("; ")
    ))
}

/// Relative path of the venv interpreter inside a sidecar directory.
fn venv_python_rel() -> &'static str {
    if cfg!(windows) {
        ".venv/Scripts/python.exe"
    } else {
        ".venv/bin/python"
    }
}

/// Best-effort sidecar dir for an explicit interpreter override: walk up from
/// `.venv/Scripts/python.exe` to the directory containing `.venv`.
fn default_workdir_for(python: &std::path::Path) -> Option<PathBuf> {
    let mut dir = python.parent()?;
    while let Some(parent) = dir.parent() {
        if dir.file_name().is_some_and(|n| n == ".venv") {
            return Some(parent.to_path_buf());
        }
        dir = parent;
    }
    None
}
