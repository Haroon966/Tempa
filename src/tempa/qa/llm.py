"""QA LLM routing — Groq by default, Claude for deep review."""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)

_DEEP_REVIEW_SYSTEM = (
    "Senior code reviewer. Return JSON array of findings with keys: "
    "severity (critical|important|suggestion), title, file, line, body, suggestion."
)


async def groq_complete(messages: list[dict[str, str]], *, max_tokens: int = 2048) -> str:
    from tempa.router.groq_router import get_router

    router = get_router()
    response = await asyncio.to_thread(
        router.chat_completion,
        category="reasoning",
        messages=messages,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


async def deep_review_complete(user_prompt: str, *, max_tokens: int = 4096) -> str:
    """Deep review always prefers Claude; falls back to Groq if Claude is unavailable."""
    from tempa.qa.claude import claude_complete, claude_configured

    if claude_configured():
        try:
            return await claude_complete(
                system=_DEEP_REVIEW_SYSTEM,
                user=user_prompt,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            log.warning("Claude deep review failed, falling back to Groq: %s", exc)

    messages = [
        {"role": "system", "content": _DEEP_REVIEW_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]
    return await groq_complete(messages, max_tokens=max_tokens)
