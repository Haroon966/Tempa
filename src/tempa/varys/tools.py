from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _format_agent_block(label: str, payload: str) -> str:
    try:
        data = json.loads(payload)
        if isinstance(data, dict):
            if data.get("status") == "error":
                return f"## {label}\n{data.get('reason') or data.get('message') or payload}"
            if data.get("message"):
                return f"## {label}\n{data['message']}"
        return f"## {label}\n{json.dumps(data, ensure_ascii=False, indent=2)[:4000]}"
    except (json.JSONDecodeError, TypeError):
        return f"## {label}\n{payload[:4000]}"


async def _invoke_worker(agent: str, user_message: str, ctx: dict[str, Any], label: str) -> str | None:
    from tempa.agents.specialists import (
        run_calendar_agent,
        run_channel_agent,
        run_gmail_agent,
        run_meet_agent,
        run_pc_agent,
        run_plugin_agent,
        run_qa_agent,
    )

    runners = {
        "gmail": run_gmail_agent,
        "calendar": run_calendar_agent,
        "meet": run_meet_agent,
        "qa": run_qa_agent,
        "plugin": run_plugin_agent,
        "channel": run_channel_agent,
        "pc": run_pc_agent,
    }
    runner = runners.get(agent)
    if runner is None:
        return None
    try:
        result = await runner(user_message, ctx)
        return _format_agent_block(label, result)
    except Exception as exc:
        logger.warning("Varys %s worker failed: %s", label, exc)
        return None


async def invoke_skill_workers(user_message: str, context: dict[str, Any] | None = None) -> str:
    """Prefetch workers implied by matched skills."""
    from tempa.orchestrator.registry import filter_workers_for_context
    from tempa.skills.matcher import match_skills
    from tempa.skills.routing import workers_from_skills

    ctx = dict(context or {})
    skills = match_skills(user_message, ctx)
    if not skills:
        return ""
    worker_ids = workers_from_skills(skills)
    allowed = filter_workers_for_context(set(worker_ids), ctx)
    labels = {
        "gmail": "Gmail",
        "calendar": "Calendar",
        "meet": "Meetings",
        "qa": "QA",
        "plugin": "Jira",
        "channel": "Slack",
        "pc": "PC",
    }
    parts: list[str] = []
    for wid in worker_ids:
        if wid not in allowed or wid == "rag":
            continue
        block = await _invoke_worker(wid, user_message, ctx, labels.get(wid, wid.title()))
        if block:
            parts.append(block)
    return "\n\n".join(parts)


async def invoke_runtime_tools(user_message: str, context: dict[str, Any] | None = None) -> str:
    """Run Tempa specialists/plugins when the user message needs live tool data."""
    ctx = dict(context or {})
    ctx["user_message"] = user_message

    from tempa.agents.specialists import _extract_meet_url, run_meet_agent

    if _extract_meet_url(user_message):
        try:
            result = await run_meet_agent(user_message, ctx)
            return _format_agent_block("Meetings", result)
        except Exception as exc:
            logger.warning("Varys meet join failed: %s", exc)

    skill_blocks = await invoke_skill_workers(user_message, ctx)
    if skill_blocks:
        return skill_blocks

    from tempa.agents.intent import (
        wants_calendar_full,
        wants_gmail_full,
        wants_meeting_archive,
        wants_private_integrations,
        wants_repo_qa,
    )

    ctx = dict(context or {})
    ctx["user_message"] = user_message
    parts: list[str] = []

    if wants_gmail_full(user_message):
        from tempa.agents.specialists import run_gmail_agent

        try:
            result = await run_gmail_agent(user_message, ctx)
            parts.append(_format_agent_block("Gmail", result))
        except Exception as exc:
            logger.warning("Varys gmail tool failed: %s", exc)

    if wants_calendar_full(user_message):
        from tempa.agents.specialists import run_calendar_agent

        try:
            result = await run_calendar_agent(user_message, ctx)
            parts.append(_format_agent_block("Calendar", result))
        except Exception as exc:
            logger.warning("Varys calendar tool failed: %s", exc)

    if wants_meeting_archive(user_message):
        from tempa.agents.specialists import run_meet_agent

        try:
            result = await run_meet_agent(user_message, ctx)
            parts.append(_format_agent_block("Meetings", result))
        except Exception as exc:
            logger.warning("Varys meet tool failed: %s", exc)

    if wants_repo_qa(user_message):
        from tempa.agents.specialists import run_qa_agent

        try:
            result = await run_qa_agent(user_message, ctx)
            parts.append(_format_agent_block("QA", result))
        except Exception as exc:
            logger.warning("Varys QA tool failed: %s", exc)

    from tempa.agents.intent import wants_jira

    if wants_jira(user_message):
        from tempa.agents.specialists import run_plugin_agent

        try:
            result = await run_plugin_agent(user_message, ctx)
            parts.append(_format_agent_block("Jira", result))
        except Exception as exc:
            logger.warning("Varys Jira tool failed: %s", exc)

    from tempa.agents.intent import wants_notion

    if wants_notion(user_message):
        from tempa.agents.specialists import run_plugin_agent

        try:
            result = await run_plugin_agent(user_message, ctx)
            parts.append(_format_agent_block("Notion", result))
        except Exception as exc:
            logger.warning("Varys Notion tool failed: %s", exc)

    if ctx.get("inbound_slack") or ctx.get("channel") == "slack":
        from tempa.agents.specialists import _slack_read_query_from_context, run_channel_agent
        from tempa.channels.slack.lookup import wants_slack_read_intent, wants_slack_invite_help
        from tempa.channels.slack.recipients import wants_slack_send_intent

        read_query = _slack_read_query_from_context(user_message, ctx)
        if (
            wants_slack_read_intent(read_query)
            or wants_slack_invite_help(user_message)
            or wants_slack_send_intent(user_message)
        ):
            try:
                result = await run_channel_agent(user_message, ctx)
                if result:
                    parts.append(_format_agent_block("Slack", result))
            except Exception as exc:
                logger.warning("Varys Slack channel tool failed: %s", exc)

    # Plugin tools for explicit integration tasks not covered by prefetch.
    plugin_hints = ("plugin", "tool ", "run tool", "use tool", "web search", "search the web")
    if any(h in user_message.lower() for h in plugin_hints):
        from tempa.agents.specialists import run_plugin_agent

        try:
            result = await run_plugin_agent(user_message, ctx)
            parts.append(_format_agent_block("Plugins", result))
        except Exception as exc:
            logger.warning("Varys plugin tool failed: %s", exc)

    pc_hints = ("write file", "create file", "delete file", "on my pc", "local file")
    if any(h in user_message.lower() for h in pc_hints):
        from tempa.agents.specialists import run_pc_agent

        try:
            result = await run_pc_agent(user_message, ctx)
            parts.append(_format_agent_block("PC", result))
        except Exception as exc:
            logger.warning("Varys PC tool failed: %s", exc)

    if wants_private_integrations(user_message) and not parts:
        from tempa.agents.specialists import run_channel_agent

        try:
            result = await run_channel_agent(user_message, ctx)
            if result:
                parts.append(_format_agent_block("Channel", result))
        except Exception as exc:
            logger.warning("Varys channel tool failed: %s", exc)

    return "\n\n".join(parts)
