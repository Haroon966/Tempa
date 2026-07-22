from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from tempa.core.chat_errors import sanitize_user_error
from tempa.hermes.skills_bridge import (
    ensure_seed_skills,
    format_active_skills_for_prompt,
    record_plan_outcome,
)
from tempa.hermes.goals import open_goals_prompt_block
from tempa.hermes.tools import build_tempa_tool_context, run_tempa_tool

logger = logging.getLogger(__name__)

_SYSTEM_POLICY = """You are Tempa's tools coordinator (Hermes runtime).
You handle Gmail, Calendar, Meet status, Slack/WhatsApp messaging drafts, memory, and approvals.
You do NOT write code, open PRs, or run Cursor — coding is owned by Tempa's Cursor job queue.
Product/data questions ("check if the count…", dashboard numbers) are investigations, not QA lint scans.
QA scans require strong intent (scan, run qa, audit, deep review) or explicit github.com / owner/repo + review wording.
Destructive sends/writes must go through Tempa pending approvals — never claim they completed without approval.
Never paste raw exceptions, git fatal advice, or stack traces to the user — speak short human sentences.
Guest users only get memory/search/public tools; do not expose private mail/calendar.
"""


def hermes_available() -> bool:
    try:
        from run_agent import AIAgent  # type: ignore  # noqa: F401

        return True
    except Exception:
        try:
            from hermes_agent.run_agent import AIAgent  # type: ignore  # noqa: F401

            return True
        except Exception:
            return False


def _load_ai_agent_class() -> Any:
    try:
        from run_agent import AIAgent  # type: ignore

        return AIAgent
    except Exception:
        from hermes_agent.run_agent import AIAgent  # type: ignore

        return AIAgent


def _system_prompt(context: dict[str, Any]) -> str:
    ensure_seed_skills()
    skills_block = format_active_skills_for_prompt(context)
    goals_block = open_goals_prompt_block()
    guest = ""
    if context.get("is_guest") or context.get("slack_guest"):
        guest = "\nThis user is a GUEST — only memory/search/public tools.\n"
    channel = str(context.get("channel") or "dashboard")
    return (
        f"{_SYSTEM_POLICY}{guest}\n"
        f"Channel: {channel}\n"
        f"{skills_block}\n"
        f"{goals_block}\n"
        "Available Tempa tools: rag, gmail, calendar, meet, channel, plugin, pc, qa, "
        "create_pending_action, meet_status, memory_search.\n"
        "Use Tempa tool results provided in the user message. "
        "If you need another Tempa tool, say TOOL_REQUEST:<name>:<json_args> on its own line."
    )


async def _run_with_ai_agent(user_message: str, context: dict[str, Any], tool_ctx: str) -> str:
    AIAgent = _load_ai_agent_class()
    from tempa.settings import get_settings

    settings = get_settings()
    disabled = ["terminal", "browser"] if settings.tempa_hermes_disable_terminal else None
    prompt = (
        f"Tempa tool context (JSON/facts):\n{tool_ctx}\n\n"
        f"User request:\n{user_message}"
    )

    def _chat() -> str:
        agent = AIAgent(
            quiet_mode=True,
            skip_context_files=True,
            disabled_toolsets=disabled,
            ephemeral_system_prompt=_system_prompt(context),
            max_iterations=int(settings.tempa_hermes_max_iterations or 24),
        )
        return str(agent.chat(prompt) or "")

    return await asyncio.to_thread(_chat)


async def _run_fallback_orchestrator(user_message: str, context: dict[str, Any]) -> dict[str, Any]:
    """When hermes-agent is not installed, keep Tempa orchestrator but inject Hermes skills."""
    from tempa.orchestrator.agent import run_orchestrator

    ensure_seed_skills()
    ctx = dict(context or {})
    ctx["active_skills_prompt"] = format_active_skills_for_prompt(ctx)
    ctx["hermes_fallback"] = True
    result = await run_orchestrator(user_message, ctx)
    # orchestrator already runs schedule_after_turn
    return result


async def run_hermes_coordinator(
    user_message: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ctx = dict(context or {})
    ensure_seed_skills()

    try:
        tool_bundle = await build_tempa_tool_context(user_message, ctx)
        tool_ctx = json.dumps(tool_bundle, ensure_ascii=False)[:12000]

        if hermes_available():
            reply = await _run_with_ai_agent(user_message, ctx, tool_ctx)
            # Optional follow-up tool lines
            if "TOOL_REQUEST:" in reply:
                for line in reply.splitlines():
                    if not line.startswith("TOOL_REQUEST:"):
                        continue
                    parts = line[len("TOOL_REQUEST:") :].split(":", 1)
                    if len(parts) != 2:
                        continue
                    name, args_raw = parts[0].strip(), parts[1].strip()
                    try:
                        args = json.loads(args_raw) if args_raw else {}
                    except json.JSONDecodeError:
                        args = {"raw": args_raw}
                    tool_bundle[name] = await run_tempa_tool(name, args, ctx)
                tool_ctx = json.dumps(tool_bundle, ensure_ascii=False)[:12000]
                reply = await _run_with_ai_agent(user_message, ctx, tool_ctx)

            from tempa.agents.graph import collect_pending_from_results
            from tempa.core.pending_actions import needs_owner_pause

            results = {k: (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)) for k, v in tool_bundle.items()}
            pending = collect_pending_from_results(results)
            paused = needs_owner_pause(pending)
            record_plan_outcome(
                user_message,
                success=not paused and bool(reply.strip()),
                notes="hermes_ai_agent",
                planned_steps=list(tool_bundle.keys()),
            )
            from tempa.orchestrator.format import format_response_for_channel
            from tempa.learning.loop import schedule_after_turn

            formatted = format_response_for_channel(reply.strip(), ctx)
            schedule_after_turn(
                user_message,
                success=not paused and bool(reply.strip()),
                paused=paused,
                matched_skills=list(ctx.get("matched_skills") or []),
                planned_steps=[{"agent": k, "task": k} for k in tool_bundle if not str(k).startswith("_")],
                response=formatted,
                notes="hermes_ai_agent",
                context=ctx,
            )

            return {
                "response": formatted,
                "sources": list(ctx.get("rag_sources") or []),
                "paused": paused,
                "pending_actions": pending,
                "artifacts": [],
                "planned_steps": [{"agent": k, "task": k} for k in tool_bundle if not str(k).startswith("_")],
            }

        logger.warning("TEMPA_COORDINATOR=hermes but hermes-agent not installed; using orchestrator fallback")
        return await _run_fallback_orchestrator(user_message, ctx)
    except Exception as exc:
        logger.exception("Hermes coordinator failed")
        return {
            "response": sanitize_user_error(exc),
            "sources": [],
            "paused": False,
            "pending_actions": [],
            "artifacts": [],
            "planned_steps": [],
        }
