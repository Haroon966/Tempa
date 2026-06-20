from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import yaml
from groq import AsyncGroq, Groq

from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_VALID_ROLES = frozenset({"user", "assistant", "system", "tool"})
_ROLE_ALIASES = {"human": "user", "ai": "assistant", "bot": "assistant"}


def normalize_groq_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for msg in messages:
        role = str(msg.get("role", "user")).lower()
        role = _ROLE_ALIASES.get(role, role)
        if role not in _VALID_ROLES:
            role = "user"
        content = msg.get("content", "")
        if content is None:
            content = ""
        if not isinstance(content, str):
            content = str(content)
        row: dict[str, Any] = {"role": role, "content": content}
        if role == "tool" and msg.get("tool_call_id"):
            row["tool_call_id"] = str(msg["tool_call_id"])
        if role == "assistant" and msg.get("tool_calls"):
            row["tool_calls"] = msg["tool_calls"]
        normalized.append(row)
    return normalized

TASK_CATEGORIES = (
    "reasoning",
    "tool_use",
    "text",
    "stt",
    "safety",
    "multilingual",
)


class GroqModelRouter:
    """Route inference tasks to Groq models with fallback chains."""

    def __init__(self, config_path: Path | None = None) -> None:
        settings = get_settings()
        path = config_path or settings.config_dir / "groq_models.yaml"
        with path.open(encoding="utf-8") as f:
            self._config = yaml.safe_load(f)
        self._api_key_env = self._config.get("api_key_env", "GROQ_API_KEY")
        self._chains: dict[str, list[str]] = self._config.get("chains", {})
        self._client: Groq | None = None
        self._async_client: AsyncGroq | None = None

    def _api_key(self) -> str:
        settings = get_settings()
        key = settings.load_groq_api_key()
        if not key:
            raise RuntimeError(f"{self._api_key_env} is not configured")
        return key

    @property
    def client(self) -> Groq:
        if self._client is None:
            self._client = Groq(api_key=self._api_key())
        return self._client

    @property
    def async_client(self) -> AsyncGroq:
        if self._async_client is None:
            self._async_client = AsyncGroq(api_key=self._api_key())
        return self._async_client

    def refresh_client(self) -> None:
        key = self._api_key()
        self._client = Groq(api_key=key)
        self._async_client = AsyncGroq(api_key=key)

    def chain_for(self, category: str) -> list[str]:
        if category not in self._chains:
            raise KeyError(f"Unknown task category: {category}")
        return list(self._chains[category])

    def route(self, category: str) -> str:
        chain = self.chain_for(category)
        if not chain:
            raise RuntimeError(f"No models configured for category: {category}")
        return chain[0]

    def chat_completion(
        self,
        *,
        category: str = "text",
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> Any:
        last_error: Exception | None = None
        payload_messages = normalize_groq_messages(messages)
        for model in self.chain_for(category):
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": payload_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"
                if response_format:
                    kwargs["response_format"] = response_format
                return self.client.chat.completions.create(**kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Groq model %s failed: %s", model, exc)
                last_error = exc
        raise RuntimeError(f"All Groq models failed for {category}") from last_error

    async def chat_completion_stream(
        self,
        *,
        category: str = "text",
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        last_error: Exception | None = None
        payload_messages = normalize_groq_messages(messages)
        for model in self.chain_for(category):
            try:
                stream = await self.async_client.chat.completions.create(
                    model=model,
                    messages=payload_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        yield delta
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("Groq stream model %s failed: %s", model, exc)
                last_error = exc
        raise RuntimeError(f"All Groq models failed for {category}") from last_error

    def test_connection(self) -> dict[str, str]:
        response = self.chat_completion(
            category="text",
            messages=[{"role": "user", "content": "Reply with exactly: ok"}],
            max_tokens=8,
        )
        content = response.choices[0].message.content or ""
        return {"status": "ok", "model": response.model, "reply": content.strip()}

    def transcribe_file(self, audio_path: Path, *, category: str = "stt") -> str:
        model = self.route(category)
        with audio_path.open("rb") as audio_file:
            result = self.client.audio.transcriptions.create(
                file=(audio_path.name, audio_file.read()),
                model=model,
            )
        return getattr(result, "text", str(result))


_router: GroqModelRouter | None = None


def get_router() -> GroqModelRouter:
    global _router
    if _router is None:
        _router = GroqModelRouter()
    return _router
