"""Anthropic Claude API for deep PR reviews."""

from __future__ import annotations

import logging

import httpx

from tempa.settings import get_settings

log = logging.getLogger(__name__)


def claude_configured() -> bool:
    return bool(get_settings().anthropic_api_key.strip())


async def claude_complete(
    *,
    system: str,
    user: str,
    max_tokens: int = 4096,
) -> str:
    settings = get_settings()
    api_key = settings.anthropic_api_key.strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    model = settings.tempa_qa_claude_model.strip() or "claude-sonnet-4-20250514"
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        response.raise_for_status()
        data = response.json()
        blocks = data.get("content") or []
        text_parts = [str(b.get("text", "")) for b in blocks if b.get("type") == "text"]
        text = "".join(text_parts).strip()
        if not text:
            raise RuntimeError("Claude returned empty response")
        log.info("qa.claude.complete model=%s chars=%s", model, len(text))
        return text
