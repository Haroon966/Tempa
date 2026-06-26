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


async def invoke_runtime_tools(user_message: str, context: dict[str, Any] | None = None) -> str:
    """Run Tempa specialists/plugins when the user message needs live tool data."""
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
