from __future__ import annotations

import json
from typing import Any

from tempa.agents.intent import is_casual_greeting, has_non_slack_tool_intent
from tempa.channels.slack.lookup import wants_slack_invite_help, wants_slack_read_intent
from tempa.channels.slack.messages import greeting_for_slack
from tempa.channels.slack.recipients import wants_slack_send_intent


def _format_channel_result(raw: str) -> str | None:
    from tempa.agents.specialists import _slack_read_reply, _slack_send_reply

    short = _slack_read_reply(raw)
    if short:
        return short
    return _slack_send_reply(raw)


async def try_slack_direct_reply(user_message: str, context: dict[str, Any]) -> str | None:
    """Return a user-facing Slack reply without LLM merge when possible."""
    if context.get("channel") != "slack" and not context.get("inbound_slack"):
        return None

    if is_casual_greeting(user_message):
        return greeting_for_slack(context)

    if has_non_slack_tool_intent(user_message):
        return None

    from tempa.agents.specialists import _slack_read_query_from_context, run_channel_agent

    ctx = {**context, "user_message": user_message}
    read_query = _slack_read_query_from_context(user_message, ctx)
    needs_channel = (
        wants_slack_read_intent(read_query)
        or wants_slack_invite_help(user_message)
        or wants_slack_send_intent(user_message)
    )
    if not needs_channel:
        return None

    result = await run_channel_agent(user_message, ctx)
    if not result:
        return None
    direct = _format_channel_result(result)
    if direct:
        return direct

    try:
        payload = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(payload, dict) and payload.get("status") == "error":
        return str(payload.get("reason") or "I couldn't complete that Slack request — try rephrasing.")
    return None
