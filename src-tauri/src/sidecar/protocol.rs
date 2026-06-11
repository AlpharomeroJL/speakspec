//! Wire types for Contract B: Rust <-> Python sidecar NDJSON protocol.
//!
//! Mirrors `sidecar/speakspec/messages.py`. One request line down produces a
//! stream of tagged response lines back, terminated by `result` or `error`.

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// A single request written to the sidecar's stdin as one JSON line.
#[derive(Debug, Clone, Serialize)]
pub struct SidecarRequest {
    /// Unique id; every response line for this request carries it back.
    pub id: String,
    /// Handler name registered in the sidecar, e.g. `ping`, `transcribe`.
    pub method: String,
    /// Handler-specific parameters.
    pub params: Value,
}

/// Structured error payload from the sidecar. Never a raw traceback.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SidecarErrorBody {
    /// Stable machine-readable code, e.g. `unknown-method`, `internal`.
    pub code: String,
    /// Human-readable description of the failure.
    pub message: String,
    /// Optional extra context for diagnostics or UI.
    #[serde(default)]
    pub details: Value,
}

/// One response line read from the sidecar's stdout.
#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum SidecarMsg {
    /// A streamed model-output fragment.
    Token {
        /// Request id this token belongs to.
        id: String,
        /// Token payload; at minimum `{ "text": "..." }`.
        data: Value,
    },
    /// A non-terminal status update.
    Progress {
        /// Request id this update belongs to.
        id: String,
        /// Progress payload, handler-specific.
        data: Value,
    },
    /// Terminal success payload. Exactly one per request.
    Result {
        /// Request id being completed.
        id: String,
        /// The result value.
        data: Value,
    },
    /// Terminal failure. Exactly one per request, instead of `Result`.
    Error {
        /// Request id being failed.
        id: String,
        /// Structured error body.
        error: SidecarErrorBody,
    },
}

impl SidecarMsg {
    /// The request id this message belongs to.
    pub fn id(&self) -> &str {
        match self {
            SidecarMsg::Token { id, .. }
            | SidecarMsg::Progress { id, .. }
            | SidecarMsg::Result { id, .. }
            | SidecarMsg::Error { id, .. } => id,
        }
    }
}
