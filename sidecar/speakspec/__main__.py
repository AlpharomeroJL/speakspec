"""Entry point: ``python -m speakspec`` starts the NDJSON RPC server.

Spawned as a long-running child process by the Tauri (Rust) core. Exits when
stdin reaches EOF, which happens whenever the parent dies or shuts down, so
the sidecar can never outlive the app.
"""

import logging
import os
import sys


def _configure_stdio() -> None:
    """Force UTF-8, LF-only stdout so the NDJSON stream is byte-stable on Windows."""
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]


def _configure_logging() -> None:
    """Send all logging to stderr; stdout is reserved for protocol lines."""
    level_name = os.environ.get("SPEAKSPEC_LOG", "INFO").upper()
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> int:
    """Run the RPC server until stdin closes."""
    _configure_stdio()
    _configure_logging()
    from speakspec.handlers import HANDLERS
    from speakspec.rpc import RpcServer

    RpcServer(HANDLERS).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
