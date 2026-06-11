"""NDJSON RPC server: reads requests from stdin, streams responses to stdout.

Protocol rules (Contract B in ``docs/architecture.md``):

* stdout carries ONLY newline-delimited JSON ``Response`` lines. All logging
  goes to stderr.
* Every request ends with exactly one terminal ``result`` or ``error`` line.
* Requests run on worker threads so a long ASR/pipeline job never blocks a
  concurrent ``ping`` health check.
* stdin EOF means the Rust core is gone: finish nothing, exit promptly so no
  zombie process survives the app.
"""

import json
import logging
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pydantic import ValidationError

from speakspec.messages import ErrorBody, Request, Response, SidecarError

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any], "RequestContext"], dict[str, Any]]


class RequestContext:
    """Per-request facilities passed to every handler.

    Lets a handler stream ``progress``/``token`` messages and poll for
    cancellation without knowing anything about stdout framing.
    """

    def __init__(self, server: "RpcServer", request_id: str) -> None:
        """Bind the context to one ``request_id`` on ``server``."""
        self._server = server
        self.request_id = request_id
        self.cancelled = threading.Event()

    def emit_progress(self, data: dict[str, Any]) -> None:
        """Stream a non-terminal progress update to the Rust core."""
        self._server.emit(Response(id=self.request_id, type="progress", data=data))

    def emit_token(self, text: str, **extra: Any) -> None:
        """Stream one model-output token fragment to the Rust core."""
        self._server.emit(Response(id=self.request_id, type="token", data={"text": text, **extra}))

    def check_cancelled(self) -> bool:
        """Return True if the Rust core cancelled this request."""
        return self.cancelled.is_set()


class RpcServer:
    """Dispatches NDJSON requests to registered handlers."""

    def __init__(self, handlers: dict[str, Handler], max_workers: int = 4) -> None:
        """Create a server over ``handlers`` with a small worker pool."""
        self._handlers = handlers
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="rpc")
        self._stdout_lock = threading.Lock()
        self._contexts: dict[str, RequestContext] = {}
        self._contexts_lock = threading.Lock()

    def emit(self, msg: Response) -> None:
        """Write one response line to stdout, atomically and flushed."""
        line = msg.model_dump_json(exclude_none=True)
        with self._stdout_lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    def serve_forever(self) -> None:
        """Read requests from stdin until EOF; dispatch each to the pool."""
        logger.info("sidecar RPC server ready")
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            self._dispatch_line(line)
        logger.info("stdin closed; shutting down")
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _dispatch_line(self, line: str) -> None:
        """Parse one request line and hand it to a worker thread."""
        try:
            request = Request.model_validate(json.loads(line))
        except (json.JSONDecodeError, ValidationError) as exc:
            # Without a parseable id we still answer, so Rust never hangs.
            req_id = self._best_effort_id(line)
            logger.warning("malformed request line: %s", exc)
            self.emit(
                Response(
                    id=req_id,
                    type="error",
                    error=ErrorBody(
                        code="bad-request",
                        message="The sidecar received a malformed request line.",
                        details={"reason": str(exc)},
                    ),
                )
            )
            return

        if request.method == "cancel":
            self._handle_cancel(request)
            return

        handler = self._handlers.get(request.method)
        if handler is None:
            self.emit(
                Response(
                    id=request.id,
                    type="error",
                    error=ErrorBody(
                        code="unknown-method",
                        message=f"The sidecar has no method named '{request.method}'.",
                        details={"known_methods": sorted(self._handlers)},
                    ),
                )
            )
            return

        ctx = RequestContext(self, request.id)
        with self._contexts_lock:
            self._contexts[request.id] = ctx
        self._pool.submit(self._run_handler, handler, request, ctx)

    def _run_handler(self, handler: Handler, request: Request, ctx: RequestContext) -> None:
        """Execute a handler and emit its terminal result or error line."""
        try:
            result = handler(request.params, ctx)
            self.emit(Response(id=request.id, type="result", data=result))
        except SidecarError as exc:
            self.emit(Response(id=request.id, type="error", error=exc.to_body()))
        except Exception as exc:  # noqa: BLE001 - last-resort boundary to keep protocol alive
            logger.exception("handler '%s' crashed", request.method)
            self.emit(
                Response(
                    id=request.id,
                    type="error",
                    error=ErrorBody(
                        code="internal",
                        message=f"The '{request.method}' operation failed unexpectedly: {exc}",
                    ),
                )
            )
        finally:
            with self._contexts_lock:
                self._contexts.pop(request.id, None)

    def _handle_cancel(self, request: Request) -> None:
        """Set the cancellation flag for an in-flight request."""
        target = str(request.params.get("id", ""))
        with self._contexts_lock:
            ctx = self._contexts.get(target)
        if ctx is not None:
            ctx.cancelled.set()
        self.emit(
            Response(
                id=request.id,
                type="result",
                data={"cancelled": target, "found": ctx is not None},
            )
        )

    @staticmethod
    def _best_effort_id(line: str) -> str:
        """Recover an id from a malformed line so the reply can be routed."""
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict) and isinstance(parsed.get("id"), str):
                return parsed["id"]
        except json.JSONDecodeError:
            pass
        return "unknown"
