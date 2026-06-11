//! Tauri command surface (Contract A). The frontend calls these via
//! `src/lib/ipc.ts`; long-running work streams back through Tauri events.

use serde_json::Value;
use tauri::State;

use crate::error::AppError;
use crate::sidecar::SidecarManager;

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
