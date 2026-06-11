"""Handler registry for the sidecar RPC server.

Each handler takes ``(params, ctx)`` and returns the ``result`` payload dict.
Handlers raise ``SidecarError`` for expected failures. New capabilities
(ASR, exports) register here as they are built.
"""

from speakspec.handlers.ping import ping
from speakspec.pipeline import handle_models_list, handle_stage1, handle_stage2, handle_stage3
from speakspec.rpc import Handler

HANDLERS: dict[str, Handler] = {
    "ping": ping,
    "models.list": handle_models_list,
    "pipeline.stage1": handle_stage1,
    "pipeline.stage2": handle_stage2,
    "pipeline.stage3": handle_stage3,
}
