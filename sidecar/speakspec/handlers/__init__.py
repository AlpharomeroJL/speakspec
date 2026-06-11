"""Handler registry for the sidecar RPC server.

Each handler takes ``(params, ctx)`` and returns the ``result`` payload dict.
Handlers raise ``SidecarError`` for expected failures. New capabilities
(ASR, exports) register here as they are built.
"""

from speakspec.asr import handle_hardware, handle_transcribe
from speakspec.exports import handle_export_bundle
from speakspec.firstrun import handle_models_pull, handle_system_hardware
from speakspec.handlers.artifacts import handle_write_agents_md
from speakspec.handlers.ping import ping
from speakspec.pipeline import handle_models_list, handle_stage1, handle_stage2, handle_stage3
from speakspec.rpc import Handler

HANDLERS: dict[str, Handler] = {
    "ping": ping,
    "models.list": handle_models_list,
    "models.pull": handle_models_pull,
    "pipeline.stage1": handle_stage1,
    "pipeline.stage2": handle_stage2,
    "pipeline.stage3": handle_stage3,
    "artifacts.agents_md": handle_write_agents_md,
    "transcribe": handle_transcribe,
    "asr.hardware": handle_hardware,
    "system.hardware": handle_system_hardware,
    "export.bundle": handle_export_bundle,
}
