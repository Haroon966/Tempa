"""Tool wrappers over existing Tempa specialists (context via ContextVar)."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_run_context: ContextVar[dict[str, Any]] = ContextVar("tempa_adk_run_context", default={})
_collected_sources: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "tempa_adk_sources",
    default=None,
)


def set_run_context(context: dict[str, Any]) -> None:
    _run_context.set(dict(context or {}))
    _collected_sources.set([])


def get_collected_sources() -> list[dict[str, Any]]:
    return list(_collected_sources.get() or [])


def _ctx() -> dict[str, Any]:
    return dict(_run_context.get() or {})


async def rag_search(task: str) -> str:
    """Search Tempa unified memory (RAG) and return an answer for the task."""
    from tempa.agents.specialists import run_rag_agent_task

    answer, sources = await run_rag_agent_task(task, _ctx())
    bucket = list(_collected_sources.get() or [])
    for src in sources or []:
        if src not in bucket:
            bucket.append(src)
    _collected_sources.set(bucket)
    return str(answer or "").strip() or "(no RAG answer)"


async def gmail_task(task: str) -> str:
    """Run Gmail specialist work (search, draft, summarize inbox) for the task."""
    from tempa.agents.specialists import run_gmail_agent

    return str(await run_gmail_agent(task, _ctx()) or "").strip() or "(no gmail result)"


async def calendar_task(task: str) -> str:
    """Run Calendar specialist work (list, create, update events) for the task."""
    from tempa.agents.specialists import run_calendar_agent

    return str(await run_calendar_agent(task, _ctx()) or "").strip() or "(no calendar result)"
