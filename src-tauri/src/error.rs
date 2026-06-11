//! Serializable, human-readable error type returned by every Tauri command.

use serde::Serialize;

/// Error surfaced to the frontend. Always a stable `code` plus a message a
/// person can act on — never a raw stack trace.
#[derive(Debug, Clone, Serialize)]
pub struct AppError {
    /// Stable machine-readable error code, e.g. `sidecar-unavailable`.
    pub code: String,
    /// Human-readable description of what went wrong and what to do.
    pub message: String,
}

impl AppError {
    /// Build an error from a stable code and human-readable message.
    pub fn new(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
        }
    }
}

impl std::fmt::Display for AppError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for AppError {}

impl From<anyhow::Error> for AppError {
    fn from(err: anyhow::Error) -> Self {
        // `{:#}` flattens the context chain into one readable sentence.
        Self::new("internal", format!("{err:#}"))
    }
}
