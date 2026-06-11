"""Health-check handler proving the full IPC round trip."""

import sys
from typing import Any

from speakspec import __version__
from speakspec.rpc import RequestContext


def ping(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """Echo ``params`` back after streaming one progress message.

    Used by the Rust core as a health check after spawn/restart, and by the
    Phase 2 end-to-end verification (frontend -> Rust -> sidecar -> back).
    """
    ctx.emit_progress({"note": "ping received; sidecar alive", "seq": 1})
    return {
        "pong": True,
        "echo": params,
        "sidecar_version": __version__,
        "python": sys.version.split()[0],
    }
