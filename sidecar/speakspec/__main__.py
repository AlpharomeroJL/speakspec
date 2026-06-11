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


def _preload_ml_stack() -> None:
    """Import the heavy ML extensions on the MAIN thread, eagerly.

    Loading numpy/ctranslate2 C extensions lazily inside a worker thread of a
    console-less, pipe-stdio child process deadlocks in the Windows loader
    (observed: numpy multiarray DLL init frozen indefinitely). Importing here,
    before the worker pool exists, makes later in-thread use safe. Failure is
    non-fatal: transcription then reports a structured error instead.
    """
    import logging

    try:
        import ctranslate2  # noqa: F401  (pulls in numpy)
        import faster_whisper  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - degraded mode, not a crash
        logging.getLogger(__name__).warning("ML stack preload failed: %s", exc)


def main() -> int:
    """Run the RPC server until stdin closes."""
    _configure_stdio()
    _configure_logging()
    _preload_ml_stack()
    from speakspec.handlers import HANDLERS
    from speakspec.rpc import RpcServer

    RpcServer(HANDLERS).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
