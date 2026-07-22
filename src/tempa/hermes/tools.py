from __future__ import annotations

import json
import logging
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

# Named Tempa tools Hermes can request (Phase 1 plugin surface).
TEMPA_TOOL_NAMES = frozenset(
    {
        "rag",
        "gmail",
        "calendar",
        "meet",
        "channel",
        "plugin",
        "pc",
        "qa",
        "create_pending_action",
        "meet_status",
        "memory_search",
    }
)


async def build_tempa_tool_context(user_message: str, context: dict[str, Any]) -> dict[str, Any]:
    """Run Tempa specialists for Hermes to reason over (no Cursor coding)."""
    from tempa.agents.graph import _run_specialist_with_retry
    from tempa.orchestrator.planner import plan_orchestrator_tasks
    from tempa.skills.matcher import match_skills
    from tempa.skills.prompt import format_skills_for_prompt

    ctx = dict(context)
    skills = match_skills(user_message, ctx)
    ctx["matched_skills"] = [s.name for s in skills]
    ctx["active_skills_prompt"] = format_skills_for_prompt(skills)

    subtasks = plan_orchestrator_tasks(user_message, ctx)
    others = [t for t in subtasks if t.get("agent") != "rag"][:4]
    rag_task = next((t for t in subtasks if t.get("agent") == "rag"), None)

    bundle: dict[str, Any] = {"_available_tools": sorted(TEMPA_TOOL_NAMES)}
    if rag_task:
        bundle["rag"] = await _run_specialist_with_retry(
            "rag",
            str(rag_task.get("task") or user_message),
            ctx,
            user_message,
            "",
            "rag",
        )
        if ctx.get("rag_sources"):
            context["rag_sources"] = ctx.get("rag_sources")

    for task in others:
        agent = str(task.get("agent") or "")
        if not agent or (agent == "qa" and not _strong_qa_intent(user_message)):
            continue
        try:
            bundle[agent] = await _run_specialist_with_retry(
                agent,
                str(task.get("task") or user_message),
                ctx,
                user_message,
                "",
                agent,
            )
        except Exception as exc:
            logger.warning("Tempa tool %s failed: %s", agent, exc)
            bundle[agent] = json.dumps({"status": "error", "reason": str(exc)[:200]})
    return bundle


def _strong_qa_intent(message: str) -> bool:
    lower = message.lower()
    return any(
        k in lower
        for k in ("scan", "run qa", "audit", "deep review", "lint", "security review")
    ) or ("github.com" in lower and any(k in lower for k in ("review", "test", "qa")))


async def _tool_create_pending_action(args: dict[str, Any], context: dict[str, Any]) -> str:
    from tempa.core.pending_actions import create_pending_action

    action_type = str(args.get("type") or args.get("action_type") or "").strip()
    payload = args.get("payload") if isinstance(args.get("payload"), dict) else dict(args)
    payload.pop("type", None)
    payload.pop("action_type", None)
    risk = str(args.get("risk_level") or "high")
    title = str(args.get("title") or "")
    source = str(context.get("channel") or "hermes")
    try:
        record = create_pending_action(
            action_type,
            payload,
            source_channel=source,
            risk_level=risk,
            title=title,
        )
        return json.dumps({"status": "pending", "pending_action_id": record["id"], **record}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "reason": str(exc)[:200]})


async def _tool_meet_status(args: dict[str, Any], context: dict[str, Any]) -> str:
    try:
        from tempa.meet.job_store import get_all_job_statuses

        statuses = get_all_job_statuses()
        items = list(statuses.items())[: int(args.get("limit") or 10)]
        jobs = [{"meeting_id": mid, **(fields if isinstance(fields, dict) else {})} for mid, fields in items]
        return json.dumps({"status": "ok", "jobs": jobs}, ensure_ascii=False, default=str)
    except Exception as exc:
        return json.dumps({"status": "error", "reason": str(exc)[:200]})


async def _tool_memory_search(args: dict[str, Any], context: dict[str, Any]) -> str:
    from tempa.agents.graph import _run_specialist_with_retry

    query = str(args.get("query") or args.get("task") or "")
    return await _run_specialist_with_retry("rag", query, context, query, "", "rag")


_SPECIAL_TOOLS: dict[str, Callable[[dict[str, Any], dict[str, Any]], Awaitable[str]]] = {
    "create_pending_action": _tool_create_pending_action,
    "meet_status": _tool_meet_status,
    "memory_search": _tool_memory_search,
}


async def run_tempa_tool(name: str, args: dict[str, Any], context: dict[str, Any]) -> Any:
    """On-demand Tempa tool for Hermes TOOL_REQUEST lines."""
    name = (name or "").strip()
    if name not in TEMPA_TOOL_NAMES:
        return json.dumps({"status": "error", "reason": f"Unknown tool: {name}"})
    special = _SPECIAL_TOOLS.get(name)
    if special:
        return await special(args, context)
    from tempa.agents.graph import _run_specialist_with_retry

    task = str(args.get("task") or args.get("query") or json.dumps(args, ensure_ascii=False))
    return await _run_specialist_with_retry(name, task, context, task, "", name)
