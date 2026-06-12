//! User settings persisted under the app data directory.

use std::path::PathBuf;

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};

/// Persisted user preferences surfaced in the Settings screen.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct AppSettings {
    pub default_model: Option<String>,
    /// `auto`, `cuda`, or `cpu`.
    pub asr_device: String,
    pub vram_override_gb: Option<f64>,
    pub ollama_url: String,
    pub interview_auto_mode: bool,
    pub cloud_stage3_enabled: bool,
    /// `openai` or `anthropic`.
    pub cloud_provider: String,
    pub cloud_api_key: Option<String>,
    pub fast_pipeline: bool,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            default_model: None,
            asr_device: "auto".into(),
            vram_override_gb: None,
            ollama_url: "http://localhost:11434".into(),
            interview_auto_mode: false,
            cloud_stage3_enabled: false,
            cloud_provider: "openai".into(),
            cloud_api_key: None,
            fast_pipeline: false,
        }
    }
}

/// Load settings from disk, returning defaults when missing.
pub fn load_settings(app: &AppHandle) -> Result<AppSettings> {
    let path = settings_path(app)?;
    if !path.is_file() {
        return Ok(AppSettings::default());
    }
    let text = std::fs::read_to_string(&path).with_context(|| format!("read {}", path.display()))?;
    serde_json::from_str(&text).context("settings.json is not valid JSON")
}

/// Persist settings to disk.
pub fn save_settings(app: &AppHandle, settings: &AppSettings) -> Result<()> {
    let path = settings_path(app)?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("create {}", parent.display()))?;
    }
    let text = serde_json::to_string_pretty(settings).context("encode settings")?;
    std::fs::write(&path, text).with_context(|| format!("write {}", path.display()))
}

/// Path to the JSON file the Python sidecar reads via ``SPEAKSPEC_CONFIG``.
pub fn sidecar_config_path(app: &AppHandle) -> Result<PathBuf> {
    let data = app.path().app_data_dir().map_err(|e| anyhow::anyhow!("{e}"))?;
    Ok(data.join("speakspec-config.json"))
}

/// Write the transient sidecar config consumed by ``get_config()`` in Python.
pub fn write_sidecar_config(app: &AppHandle, settings: &AppSettings) -> Result<PathBuf> {
    let path = sidecar_config_path(app)?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("create {}", parent.display()))?;
    }
    let payload = serde_json::json!({
        "ollama_url": settings.ollama_url,
        "default_model": settings.default_model,
        "asr_device": settings.asr_device,
        "vram_override_gb": settings.vram_override_gb,
        "interview_auto_mode": settings.interview_auto_mode,
        "cloud_stage3_enabled": settings.cloud_stage3_enabled,
        "cloud_provider": settings.cloud_provider,
        "cloud_api_key": settings.cloud_api_key,
        "fast_pipeline": settings.fast_pipeline,
    });
    std::fs::write(&path, serde_json::to_string_pretty(&payload)?)
        .with_context(|| format!("write {}", path.display()))?;
    Ok(path)
}

fn settings_path(app: &AppHandle) -> Result<PathBuf> {
    let data = app.path().app_data_dir().map_err(|e| anyhow::anyhow!("{e}"))?;
    Ok(data.join("settings.json"))
}

/// Apply bundled-runtime path env vars when the release layout is present.
pub fn apply_runtime_env(cmd: &mut tokio::process::Command, app: &AppHandle) {
    let Ok(resource_dir) = app.path().resource_dir() else {
        return;
    };
    let runtime = resource_dir.join("speakspec-runtime");
    if !runtime.is_dir() {
        return;
    }
    set_path_env(cmd, "SPEAKSPEC_TEMPLATES_DIR", runtime.join("templates"));
    set_path_env(cmd, "SPEAKSPEC_MODELS_CONFIG", runtime.join("config/models.json"));
    set_path_env(cmd, "SPEAKSPEC_SCHEMA_DIR", runtime.join("docs/schemas"));
    set_path_env(cmd, "SPEAKSPEC_VOCAB_FILE", runtime.join("dicts/tech-vocab.json"));
    set_path_env(cmd, "SPEAKSPEC_NODE", runtime.join("node/node.exe"));
    set_path_env(
        cmd,
        "SPEAKSPEC_MERMAID_VALIDATOR",
        runtime.join("tools/mermaid-validate/validate.mjs"),
    );
}

fn set_path_env(cmd: &mut tokio::process::Command, key: &str, path: PathBuf) {
    if path.exists() {
        cmd.env(key, path);
    }
}

/// Apply user settings as env vars for the sidecar child process.
pub fn apply_settings_env(cmd: &mut tokio::process::Command, app: &AppHandle) {
    let settings = load_settings(app).unwrap_or_default();
    if let Ok(config_path) = write_sidecar_config(app, &settings) {
        cmd.env("SPEAKSPEC_CONFIG", config_path);
    }
    if let Some(model) = &settings.default_model {
        if !model.is_empty() {
            cmd.env("SPEAKSPEC_DEFAULT_MODEL", model);
        }
    }
    if settings.asr_device != "auto" {
        cmd.env("SPEAKSPEC_ASR_DEVICE", &settings.asr_device);
    }
}
