"""Contract C: HTTP client for the local Ollama server.

Every generation request sets ``format`` (the stage's JSON schema),
``temperature``, and ``num_ctx`` explicitly — the Ollama ``num_ctx`` default
of 4096 silently truncates transcripts and must never be relied on.
"""

import json
import logging
from collections.abc import Callable

import httpx

from speakspec.messages import SidecarError

logger = logging.getLogger(__name__)

OLLAMA_INSTALL_HINT = (
    "Ollama is not reachable. Install it from https://ollama.com/download and "
    "make sure it is running, then try again."
)

# Model families that support the chat-API "think" toggle; thinking is
# disabled for structured generation so reasoning text never pollutes JSON.
_THINKING_FAMILIES = ("qwen3", "deepseek-r1", "magistral", "gpt-oss")


def _is_thinking_model(model: str) -> bool:
    """Whether the model family supports (and defaults to) thinking output."""
    base = model.lower()
    return any(base.startswith(family) for family in _THINKING_FAMILIES)


class OllamaClient:
    """Thin httpx wrapper over the local Ollama HTTP API."""

    def __init__(self, base_url: str) -> None:
        """Create a client for ``base_url`` (e.g. http://localhost:11434)."""
        self.base_url = base_url.rstrip("/")
        # Generation can legitimately take minutes (cold model load + long
        # outputs); only connecting gets a short timeout.
        self._timeout = httpx.Timeout(connect=5.0, read=600.0, write=30.0, pool=5.0)

    def list_models(self) -> list[dict]:
        """Return installed models from ``/api/tags`` (name, size, details)."""
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise SidecarError(
                "ollama-unavailable", OLLAMA_INSTALL_HINT, {"reason": str(exc)}
            ) from exc
        return resp.json().get("models", [])

    def chat_structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: dict,
        temperature: float,
        num_ctx: int,
        num_predict: int | None = None,
        on_token: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        """Stream a schema-constrained chat completion; return the full text.

        ``num_predict`` bounds the generation so a degenerating model fails
        fast (and validation retries can perturb it) instead of overflowing
        ``num_ctx`` and truncating mid-string.

        Raises ``SidecarError`` with a stable code for every failure mode:
        ``ollama-unavailable``, ``ollama-request-failed``, ``cancelled``.
        """
        options: dict = {"temperature": temperature, "num_ctx": num_ctx}
        if num_predict is not None:
            options["num_predict"] = num_predict
        payload: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": schema,
            "stream": True,
            "options": options,
        }
        if _is_thinking_model(model):
            payload["think"] = False
        try:
            return self._stream_chat(payload, on_token, cancelled)
        except SidecarError as exc:
            # Defensive: if the think toggle was rejected, retry once without.
            if "think" in payload and "think" in str(exc.details.get("body", "")).lower():
                payload.pop("think")
                return self._stream_chat(payload, on_token, cancelled)
            raise

    def pull_model(
        self,
        name: str,
        on_progress: Callable[[dict], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        """Pull a model via ``/api/pull``, streaming progress.

        Progress dicts carry ``status`` and, when downloading, ``total`` and
        ``completed`` bytes (the UI derives percent/ETA). Ollama resumes
        partial layer downloads natively, so interruption is safe.
        """
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/api/pull",
                json={"name": name, "stream": True},
                timeout=httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0),
            ) as resp:
                if resp.status_code != 200:
                    body = resp.read().decode("utf-8", errors="replace")
                    raise SidecarError(
                        "model-pull-failed",
                        f"Ollama could not pull '{name}' (HTTP {resp.status_code}).",
                        {"body": body[:1000]},
                    )
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if cancelled is not None and cancelled():
                        raise SidecarError("cancelled", "The model download was cancelled.")
                    obj = json.loads(line)
                    if obj.get("error"):
                        raise SidecarError(
                            "model-pull-failed",
                            f"Ollama reported an error pulling '{name}': {obj['error']}",
                        )
                    if on_progress is not None:
                        on_progress(obj)
        except httpx.HTTPError as exc:
            raise SidecarError(
                "ollama-unavailable", OLLAMA_INSTALL_HINT, {"reason": str(exc)}
            ) from exc

    def _stream_chat(
        self,
        payload: dict,
        on_token: Callable[[str], None] | None,
        cancelled: Callable[[], bool] | None,
    ) -> str:
        """POST ``/api/chat`` and accumulate streamed message content."""
        chunks: list[str] = []
        try:
            with httpx.stream(
                "POST", f"{self.base_url}/api/chat", json=payload, timeout=self._timeout
            ) as resp:
                if resp.status_code != 200:
                    body = resp.read().decode("utf-8", errors="replace")
                    raise SidecarError(
                        "ollama-request-failed",
                        f"Ollama rejected the request (HTTP {resp.status_code}). "
                        f"Model: {payload['model']}.",
                        {"body": body[:2000]},
                    )
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if cancelled is not None and cancelled():
                        raise SidecarError("cancelled", "The request was cancelled.")
                    obj = json.loads(line)
                    if obj.get("error"):
                        raise SidecarError(
                            "ollama-request-failed",
                            f"Ollama reported an error: {obj['error']}",
                            {"body": str(obj)[:2000]},
                        )
                    piece = obj.get("message", {}).get("content", "")
                    if piece:
                        chunks.append(piece)
                        if on_token is not None:
                            on_token(piece)
                    if obj.get("done"):
                        break
        except httpx.HTTPError as exc:
            raise SidecarError(
                "ollama-unavailable", OLLAMA_INSTALL_HINT, {"reason": str(exc)}
            ) from exc
        return "".join(chunks)
