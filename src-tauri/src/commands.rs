//! Tauri command surface (Contract A). The frontend calls these via
//! `src/lib/ipc.ts`; long-running work streams back through Tauri events.

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, State};

use crate::audio::AudioController;
use crate::error::AppError;
use crate::sidecar::{events, SidecarManager};

/// Round-trip health check: frontend -> Rust -> Python sidecar -> back.
///
/// The sidecar streams a `progress` line (forwarded as the
/// `sidecar://progress` event) before returning the pong payload.
#[tauri::command]
pub async fn ping_sidecar(
    sidecar: State<'_, SidecarManager>,
    payload: Option<Value>,
) -> Result<Value, AppError> {
    sidecar
        .request("ping", payload.unwrap_or_else(|| serde_json::json!({})))
        .await
}

/// Ask the sidecar to cancel an in-flight request by its id.
#[tauri::command]
pub async fn cancel_sidecar_request(
    sidecar: State<'_, SidecarManager>,
    request_id: String,
) -> Result<Value, AppError> {
    sidecar.cancel(&request_id).await
}

/// Print a frontend-originated line to the dev console. Exists so automated
/// end-to-end checks can prove data reached the webview (the dev log shows
/// what the frontend received).
#[tauri::command]
pub fn frontend_log(message: String) {
    println!("[frontend] {message}");
}

/// Run one pipeline stage (1, 2, or 3) in the sidecar, wrapping it in the
/// `pipeline://stage-start` / `stage-done` / `error` lifecycle events.
/// Tokens stream separately via `pipeline://token` while this is pending.
#[tauri::command]
pub async fn run_pipeline_stage(
    app: AppHandle,
    sidecar: State<'_, SidecarManager>,
    stage: u8,
    params: Value,
) -> Result<Value, AppError> {
    let method = match stage {
        1 => "pipeline.stage1",
        2 => "pipeline.stage2",
        3 => "pipeline.stage3",
        other => {
            return Err(AppError::new(
                "bad-stage",
                format!("There is no pipeline stage {other}; valid stages are 1, 2, 3."),
            ))
        }
    };
    let _ = app.emit(events::PIPELINE_STAGE_START, json!({ "stage": stage }));
    match sidecar.request(method, params).await {
        Ok(result) => {
            let _ = app.emit(
                events::PIPELINE_STAGE_DONE,
                json!({ "stage": stage, "result": result }),
            );
            Ok(result)
        }
        Err(err) => {
            let _ = app.emit(
                events::PIPELINE_ERROR,
                json!({ "stage": stage, "code": err.code, "message": err.message }),
            );
            Err(err)
        }
    }
}

/// List installed Ollama models and the auto-selected default.
#[tauri::command]
pub async fn list_models(sidecar: State<'_, SidecarManager>) -> Result<Value, AppError> {
    sidecar.request("models.list", json!({})).await
}

/// Write the full export bundle (AGENTS.md, CLAUDE.md, ADRs, diagrams,
/// spec.md, spec.docx, spec.json) into the session directory.
#[tauri::command]
pub async fn export_bundle(
    sidecar: State<'_, SidecarManager>,
    params: Value,
) -> Result<Value, AppError> {
    sidecar.request("export.bundle", params).await
}

/// Reveal a path in the system file explorer.
#[tauri::command]
pub fn show_in_folder(path: String) -> Result<(), AppError> {
    #[cfg(windows)]
    {
        std::process::Command::new("explorer")
            .arg("/select,")
            .arg(&path)
            .spawn()
            .map_err(|e| AppError::new("internal", format!("could not open Explorer: {e}")))?;
    }
    Ok(())
}

/// Transcribe an audio file in the sidecar (faster-whisper).
/// Progress streams via `asr://progress`; returns raw + corrected
/// transcripts, segments, and the hardware path used.
#[tauri::command]
pub async fn transcribe(
    sidecar: State<'_, SidecarManager>,
    params: Value,
) -> Result<Value, AppError> {
    sidecar.request("transcribe", params).await
}

/// Report the detected ASR hardware path (GPU/CPU, chosen model).
#[tauri::command]
pub async fn asr_hardware(sidecar: State<'_, SidecarManager>) -> Result<Value, AppError> {
    sidecar.request("asr.hardware", json!({})).await
}

/// Full first-run hardware report: ASR path, VRAM, Ollama reachability,
/// installed models, and the recommended tier. Completes in <5s.
#[tauri::command]
pub async fn system_hardware(sidecar: State<'_, SidecarManager>) -> Result<Value, AppError> {
    sidecar.request("system.hardware", json!({})).await
}

/// Pull an Ollama model; percent progress streams via `sidecar://progress`.
#[tauri::command]
pub async fn pull_model(
    sidecar: State<'_, SidecarManager>,
    name: String,
) -> Result<Value, AppError> {
    sidecar.request("models.pull", json!({ "name": name })).await
}

/// Create a new session directory and start recording into it.
/// Returns the WAV path. Live levels stream via `audio://level`.
#[tauri::command]
pub fn start_recording(
    app: AppHandle,
    audio: State<'_, AudioController>,
) -> Result<Value, AppError> {
    let dir = new_session_dir(&app)?;
    let path = dir.join("recording.wav");
    audio
        .start(path.clone())
        .map_err(|message| AppError::new("audio-start-failed", message))?;
    Ok(json!({ "path": path.to_string_lossy(), "session_dir": dir.to_string_lossy() }))
}

/// Pause the current recording (stream stays open; one continuous file).
#[tauri::command]
pub fn pause_recording(audio: State<'_, AudioController>) -> Result<(), AppError> {
    audio
        .pause()
        .map_err(|message| AppError::new("audio-pause-failed", message))
}

/// Resume a paused recording.
#[tauri::command]
pub fn resume_recording(audio: State<'_, AudioController>) -> Result<(), AppError> {
    audio
        .resume()
        .map_err(|message| AppError::new("audio-resume-failed", message))
}

/// Stop recording and finalize the WAV file.
#[tauri::command]
pub fn stop_recording(audio: State<'_, AudioController>) -> Result<Value, AppError> {
    let result = audio
        .stop()
        .map_err(|message| AppError::new("audio-stop-failed", message))?;
    serde_json::to_value(&result)
        .map_err(|e| AppError::new("internal", format!("could not encode result: {e}")))
}

/// Import an existing audio file into a new session directory.
/// Validates the format by magic bytes with a per-format error message.
#[tauri::command]
pub fn import_audio(app: AppHandle, source_path: String) -> Result<Value, AppError> {
    let source = std::path::PathBuf::from(&source_path);
    if !source.is_file() {
        return Err(AppError::new(
            "file-not-found",
            format!("There is no file at {source_path}."),
        ));
    }
    let header = std::fs::read(&source)
        .map_err(|e| AppError::new("file-unreadable", format!("Could not read the file: {e}")))?;
    let extension = source
        .extension()
        .map(|e| e.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    let Some(detected) = crate::audio::sniff_audio_format(&header) else {
        return Err(AppError::new(
            "unsupported-format",
            format!(
                "'{extension}' files are not recognized audio. Supported formats: {}.",
                crate::audio::SUPPORTED_IMPORT_FORMATS.join(", ")
            ),
        ));
    };
    if !crate::audio::SUPPORTED_IMPORT_FORMATS.contains(&detected) {
        return Err(AppError::new(
            "unsupported-format",
            format!(
                "{detected} audio is not supported. Supported formats: {}.",
                crate::audio::SUPPORTED_IMPORT_FORMATS.join(", ")
            ),
        ));
    }
    let dir = new_session_dir(&app)?;
    let dest = dir.join(format!("imported.{detected}"));
    std::fs::copy(&source, &dest).map_err(|e| {
        AppError::new(
            "import-failed",
            format!("Could not copy the audio into the session: {e}"),
        )
    })?;
    Ok(json!({
        "path": dest.to_string_lossy(),
        "session_dir": dir.to_string_lossy(),
        "detected_format": detected,
    }))
}

/// Persist a completed session (called when results are ready).
#[tauri::command]
pub async fn save_session(
    store: State<'_, crate::sessions::SessionStore>,
    id: String,
    title: String,
    transcript: String,
    spec_json: String,
    dir: String,
) -> Result<(), AppError> {
    store
        .save(&id, &title, &transcript, &spec_json, &dir)
        .await
        .map_err(|e| AppError::new("session-save-failed", format!("{e:#}")))
}

/// List all sessions, newest first.
#[tauri::command]
pub async fn list_sessions(
    store: State<'_, crate::sessions::SessionStore>,
) -> Result<Value, AppError> {
    let sessions = store
        .list()
        .await
        .map_err(|e| AppError::new("session-list-failed", format!("{e:#}")))?;
    serde_json::to_value(sessions).map_err(|e| AppError::new("internal", e.to_string()))
}

/// Full-text search over session titles and transcripts.
#[tauri::command]
pub async fn search_sessions(
    store: State<'_, crate::sessions::SessionStore>,
    query: String,
) -> Result<Value, AppError> {
    let sessions = store
        .search(&query)
        .await
        .map_err(|e| AppError::new("session-search-failed", format!("{e:#}")))?;
    serde_json::to_value(sessions).map_err(|e| AppError::new("internal", e.to_string()))
}

/// Load a stored session's transcript + spec for re-opening.
#[tauri::command]
pub async fn load_session(
    store: State<'_, crate::sessions::SessionStore>,
    id: String,
) -> Result<Value, AppError> {
    let loaded = store
        .load(&id)
        .await
        .map_err(|e| AppError::new("session-load-failed", format!("{e:#}")))?;
    match loaded {
        Some((transcript, spec_json, dir)) => Ok(json!({
            "transcript": transcript,
            "spec_json": spec_json,
            "dir": dir,
        })),
        None => Err(AppError::new(
            "session-not-found",
            format!("There is no stored session with id {id}."),
        )),
    }
}

/// Delete a session: database row and every file in its directory.
#[tauri::command]
pub async fn delete_session(
    store: State<'_, crate::sessions::SessionStore>,
    id: String,
) -> Result<(), AppError> {
    store
        .delete(&id)
        .await
        .map_err(|e| AppError::new("session-delete-failed", format!("{e:#}")))
}

/// Create `<app_data>/sessions/<millis-since-epoch>/`.
fn new_session_dir(app: &AppHandle) -> Result<std::path::PathBuf, AppError> {
    let base = app
        .path()
        .app_data_dir()
        .map_err(|e| AppError::new("internal", format!("no app data directory: {e}")))?
        .join("sessions");
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    let dir = base.join(stamp.to_string());
    std::fs::create_dir_all(&dir).map_err(|e| {
        AppError::new(
            "internal",
            format!("could not create the session directory: {e}"),
        )
    })?;
    Ok(dir)
}
