"""Speakspec sidecar: local AI inference for the Speakspec desktop app.

Long-running child process spawned by the Tauri (Rust) core. Speaks
newline-delimited JSON over stdin/stdout. Hosts faster-whisper ASR and the
three-stage Ollama architecture pipeline. Nothing in this package may perform
network I/O to any host other than the local Ollama server unless the user has
explicitly enabled a cloud key in settings.
"""

__version__ = "0.1.0"
