from __future__ import annotations

from typing import Any

from tempa.channels.slack.messages import GUEST_PRIVATE_COMING_SOON


def format_response_for_channel(response: str, context: dict[str, Any] | None) -> str:
    ctx = dict(context or {})
    channel = str(ctx.get("channel") or "dashboard")

    if channel == "slack" or ctx.get("inbound_slack"):
        from tempa.channels.slack.formatting import prepare_slack_reply

        return prepare_slack_reply(response)

    if channel == "whatsapp":
        return response.strip()

    return response


def guest_blocked_message(user_message: str, context: dict[str, Any] | None) -> str | None:
    from tempa.agents.tool_policy import is_slack_guest
    from tempa.agents.intent import wants_calendar_full, wants_gmail_full, wants_meeting_archive, wants_repo_qa

    ctx = dict(context or {})
    if not is_slack_guest(ctx):
        return None
    lower = user_message.lower()
    private = (
        wants_gmail_full(user_message)
        or wants_calendar_full(user_message, include_calendar="calendar" in lower)
        or wants_meeting_archive(user_message)
        or wants_repo_qa(user_message)
        or any(k in lower for k in ("whatsapp", "inbox", "email", "calendar", "meet transcript"))
    )
    if private:
        return GUEST_PRIVATE_COMING_SOON
    return None
