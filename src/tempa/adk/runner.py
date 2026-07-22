"""Run ADK coordinator and map events to Tempa orchestrator result shape."""

from __future__ import annotations

import logging
from typing import Any

from google.genai import types

from tempa.adk.agents import build_root_agent
from tempa.adk.tools import get_collected_sources, set_run_context

logger = logging.getLogger(__name__)

_APP_NAME = "tempa_adk_spike"


def _text_from_event(event: Any) -> str:
    content = getattr(event, "content", None)
    if content is None:
        return ""
    parts = getattr(content, "parts", None) or []
    chunks: list[str] = []
    for part in parts:
        text = getattr(part, "text", None)
        if text:
            chunks.append(str(text))
    return "".join(chunks).strip()


async def run_adk_orchestrator(
    user_message: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """ADK spike entry — same keys as OrchestratorAgent.run."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    ctx = dict(context or {})
    set_run_context(ctx)

    session_service = InMemorySessionService()
    user_id = str(ctx.get("user_id") or ctx.get("slack_user_id") or "tempa")
    session_id = str(ctx.get("session_id") or "adk-spike")
    await session_service.create_session(
        app_name=_APP_NAME,
        user_id=user_id,
        session_id=session_id,
        state={"channel": str(ctx.get("channel") or "dashboard")},
    )

    root = build_root_agent()
    runner = Runner(
        app_name=_APP_NAME,
        agent=root,
        session_service=session_service,
    )

    message = types.Content(role="user", parts=[types.Part(text=user_message)])
    final_text = ""
    planned: list[dict[str, Any]] = []

    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=message,
        ):
            author = str(getattr(event, "author", "") or "")
            if author and author != "user" and author != root.name:
                step = {"agent": author, "status": "done"}
                if step not in planned:
                    planned.append(step)
            if event.is_final_response() and author == root.name:
                text = _text_from_event(event)
                if text:
                    final_text = text
            elif event.is_final_response() and not final_text:
                text = _text_from_event(event)
                if text:
                    final_text = text
    except Exception:
        logger.exception("ADK spike run failed")
        raise

    if not final_text.strip():
        final_text = "I could not produce a response via the ADK coordinator."

    from tempa.orchestrator.format import format_response_for_channel

    response = format_response_for_channel(final_text.strip(), ctx)

    return {
        "response": response,
        "sources": get_collected_sources(),
        "paused": False,
        "pending_actions": [],
        "artifacts": [],
        "planned_steps": planned,
    }
