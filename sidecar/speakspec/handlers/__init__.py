"""Handler registry for the sidecar RPC server.

Each handler takes ``(params, ctx)`` and returns the ``result`` payload dict.
Handlers raise ``SidecarError`` for expected failures. New capabilities
(ASR, pipeline stages) register here as they are built.
"""

from speakspec.handlers.ping import ping
from speakspec.rpc import Handler

HANDLERS: dict[str, Handler] = {
    "ping": ping,
}
