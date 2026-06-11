//! Speakspec core: Tauri app wiring.
//!
//! Owns the four process boundaries described in `docs/architecture.md`:
//! the webview talks to this crate via commands/events (Contract A), and this
//! crate owns the Python sidecar child process (Contract B). Contracts C
//! (Ollama) and D (faster-whisper) live inside the sidecar.

mod commands;
mod error;
pub mod pipeline_types;
pub mod sidecar;

use anyhow::Context;
use tauri::Manager;

use sidecar::SidecarManager;

/// Build and run the Tauri application. Returns an error instead of
/// panicking so `main` can print a human-readable message.
pub fn run() -> anyhow::Result<()> {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let manager = SidecarManager::new(app.handle().clone());
            app.manage(manager.clone());
            // Spawn asynchronously so the window appears immediately even if
            // the sidecar takes a moment (or fails with guidance).
            tauri::async_runtime::spawn(async move { manager.start().await });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::ping_sidecar,
            commands::cancel_sidecar_request,
            commands::frontend_log,
        ])
        .build(tauri::generate_context!())
        .context("failed to build the Tauri application")?;

    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            // Block briefly to close the sidecar's stdin (EOF -> child exits)
            // and force-kill it if it lingers. No zombies.
            if let Some(manager) = app_handle.try_state::<SidecarManager>() {
                tauri::async_runtime::block_on(manager.shutdown());
            }
        }
    });
    Ok(())
}
