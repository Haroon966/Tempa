from __future__ import annotations

from typing import Any

GREETING_NEW = "Hi — I'm Tempa. How can I help?"
GREETING_CONTINUE = "Hey — what can I help with?"

ERROR_GENERIC = "Something went wrong on my end — try again in a moment."
ERROR_EMPTY_REPLY = "I didn't catch that — could you rephrase?"

GUEST_PRIVATE_COMING_SOON = (
    "Email, calendar, WhatsApp, and meeting tools aren't available on Slack yet. "
    "I can still help with general questions and Jira tickets here."
)

ERROR_CLAUDE_RUNNER = (
    "I couldn't reach the Claude runner. Check ANTHROPIC_API_KEY or Claude Code CLI."
)

SLACK_MERGE_STYLE = (
    "Answer the user's Slack message directly with as much detail as needed. "
    "Use Slack mrkdwn only: *bold*, _italic_, `inline code`, triple-backtick code blocks. "
    "Do not use **double asterisks**, ## headers, or [text](url) links. "
    "Continue the thread naturally — do not repeat prior answers or re-introduce yourself. "
    "Do not mention merging specialists or internal tools. "
    "Do not bring up unrelated WhatsApp, email, or calendar unless they asked.\n"
)


def greeting_for_slack(context: dict[str, Any] | None) -> str:
    """Full intro for new threads; short greeting when Tempa already replied."""
    ctx = dict(context or {})
    channel_id = str(ctx.get("slack_channel_id") or "")
    conv_key = str(ctx.get("slack_conversation_key") or ctx.get("slack_thread_ts") or "")

    if channel_id and conv_key:
        from tempa.channels.slack.conversation import bot_participated_in_thread

        if bot_participated_in_thread(channel_id, conv_key):
            return GREETING_CONTINUE

    return GREETING_NEW
