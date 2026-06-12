"""Optional cloud LLM client for Stage 3 (OpenAI-compatible APIs).

Only architecture-spec text is sent — never audio. Off unless the user enables
cloud Stage 3 and provides an API key in settings.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx

from speakspec.config import get_config
from speakspec.messages import SidecarError

logger = logging.getLogger(__name__)

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


class CloudClient:
    """Thin wrapper over OpenAI- or Anthropic-compatible chat APIs."""

    def __init__(self, provider: str, api_key: str) -> None:
        """Store provider id and API key for outbound requests."""
        self.provider = provider.lower()
        self.api_key = api_key
        self._timeout = httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=5.0)

    @classmethod
    def from_config(cls) -> "CloudClient | None":
        """Build a client when cloud Stage 3 is enabled and a key is present."""
        config = get_config()
        if not config.get("cloud_stage3_enabled"):
            return None
        key = config.get("cloud_api_key")
        if not key or not str(key).strip():
            raise SidecarError(
                "cloud-key-missing",
                "Cloud Stage 3 is enabled but no API key is configured. "
                "Add a key in Settings or turn cloud Stage 3 off.",
            )
        return cls(str(config.get("cloud_provider", "openai")), str(key).strip())

    def chat_structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: dict,
        temperature: float,
        on_token: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        """Return structured JSON text from the cloud provider."""
        if self.provider == "anthropic":
            return self._anthropic_chat(
                model=model or "claude-sonnet-4-20250514",
                system=system,
                user=user,
                schema=schema,
                temperature=temperature,
                on_token=on_token,
                cancelled=cancelled,
            )
        return self._openai_chat(
            model=model or "gpt-4o-mini",
            system=system,
            user=user,
            schema=schema,
            temperature=temperature,
            on_token=on_token,
            cancelled=cancelled,
        )

    def _openai_chat(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: dict,
        temperature: float,
        on_token: Callable[[str], None] | None,
        cancelled: Callable[[], bool] | None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "stream": on_token is not None,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"schema": schema, "name": "stage3"},
            },
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            if on_token is None:
                resp = httpx.post(_OPENAI_URL, json=payload, headers=headers, timeout=self._timeout)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            return self._stream_openai(payload, headers, on_token, cancelled)
        except httpx.HTTPError as exc:
            raise SidecarError("cloud-request-failed", f"Cloud API request failed: {exc}") from exc

    def _stream_openai(
        self,
        payload: dict,
        headers: dict,
        on_token: Callable[[str], None],
        cancelled: Callable[[], bool] | None,
    ) -> str:
        parts: list[str] = []
        with httpx.stream(
            "POST", _OPENAI_URL, json=payload, headers=headers, timeout=self._timeout
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if cancelled and cancelled():
                    raise SidecarError("cancelled", "The pipeline was cancelled.")
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content", "")
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                if delta:
                    parts.append(delta)
                    on_token(delta)
        return "".join(parts)

    def _anthropic_chat(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: dict,
        temperature: float,
        on_token: Callable[[str], None] | None,
        cancelled: Callable[[], bool] | None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": 8192,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        # Anthropic structured output via tool schema approximation
        payload["tools"] = [
            {
                "name": "stage3_output",
                "description": "Stage 3 structured output",
                "input_schema": schema,
            }
        ]
        payload["tool_choice"] = {"type": "tool", "name": "stage3_output"}
        try:
            resp = httpx.post(_ANTHROPIC_URL, json=payload, headers=headers, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            for block in data.get("content", []):
                if block.get("type") == "tool_use":
                    text = json.dumps(block.get("input", {}))
                    if on_token:
                        on_token(text)
                    return text
            raise SidecarError("cloud-empty-response", "Anthropic returned no tool output.")
        except httpx.HTTPError as exc:
            raise SidecarError("cloud-request-failed", f"Cloud API request failed: {exc}") from exc
