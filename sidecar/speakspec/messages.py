"""Wire-format models for the Rust <-> Python sidecar NDJSON protocol.

One request line (Rust -> Python) produces a stream of response lines
(Python -> Rust) sharing the request ``id``, terminated by exactly one
``result`` or ``error`` line. See ``docs/architecture.md`` (Contract B).
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Request(BaseModel):
    """A single JSON-RPC-style request from the Rust core.

    ``method`` selects a handler; ``params`` is handler-specific.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class ErrorBody(BaseModel):
    """Structured, human-readable error. Never a raw traceback."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class Response(BaseModel):
    """One streamed response line.

    ``type`` is ``token`` (model output fragment), ``progress`` (status
    update), ``result`` (terminal success payload), or ``error`` (terminal
    failure). ``data`` is set for the first three; ``error`` for the last.
    """

    id: str
    type: Literal["token", "progress", "result", "error"]
    data: dict[str, Any] | None = None
    error: ErrorBody | None = None


class SidecarError(Exception):
    """Raise inside a handler to return a structured error to Rust."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        """Store the error ``code``, human-readable ``message`` and ``details``."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_body(self) -> ErrorBody:
        """Convert to the wire-format error body."""
        return ErrorBody(code=self.code, message=self.message, details=self.details)
