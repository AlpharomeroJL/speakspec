//! Tauri command surface (Contract A). The frontend calls these via
//! `src/lib/ipc.ts`; long-running work streams back through Tauri events.

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, State};

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
