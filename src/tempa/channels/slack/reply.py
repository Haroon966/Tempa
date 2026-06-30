from __future__ import annotations

import asyncio
import logging
import re
import threading

from tempa.channels.slack.context import is_dm_event, reply_thread_ts
from tempa.channels.slack.conversation import (
    conversation_thread_key,
    has_assistant_reply_for,
    record_conversation_turn,
)
from tempa.channels.slack.formatting import prepare_slack_reply
from tempa.channels.slack.ingest import ingest_slack_message
from tempa.channels.slack.messages import (
    ERROR_CLAUDE_RUNNER,
    ERROR_EMPTY_REPLY,
    ERROR_GENERIC,
    GUEST_PRIVATE_COMING_SOON,
)
from tempa.channels.slack.outbound import _split_text, send_slack_message
from tempa.channels.slack.session import mark_inbound_seen, set_error, touch_event
from tempa.channels.slack.users import is_privileged_slack_user
from tempa.core.events import event_bus

logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")


def _schedule_ingest(
    event: dict,
    *,
    user_id: str,
    channel_id: str,
    user_names: dict[str, str] | None = None,
) -> None:
    """Fire-and-forget ingest on a daemon thread (must not block pytest / event loop shutdown)."""
    threading.Thread(
        target=_ingest_inbound,
        kwargs={"event": event, "user_id": user_id, "channel_id": channel_id, "user_names": user_names},
        daemon=True,
    ).start()


def _ingest_inbound(
    event: dict,
    *,
    user_id: str,
    channel_id: str,
    user_names: dict[str, str] | None = None,
) -> None:
    try:
        ingest_slack_message(
            event,
            channel_id=channel_id,
            user_names=user_names,
            tags=["inbound"],
        )
    except Exception:
        logger.exception("Failed to index Slack message")


def _normalize_text(text: str, *, event_type: str) -> str:
    cleaned = _MENTION_RE.sub("", text or "").strip()
    cleaned = re.sub(r"<(https?://[^>|]+)(?:\|[^>]+)?>", r"\1", cleaned)
    return cleaned.strip()


async def _post_slack_reply(
    channel_id: str,
    text: str,
    *,
    reply_thread: str,
    say=None,
) -> dict:
    formatted = prepare_slack_reply(text)
    chunks = _split_text(formatted)
    if say is not None:
        for chunk in chunks:
            kwargs: dict = {"text": chunk}
            if reply_thread:
                kwargs["thread_ts"] = reply_thread
            await say(**kwargs)
        return {"status": "sent", "via": "say", "chunks": len(chunks)}
    return await send_slack_message(
        channel_id,
        text,
        thread_ts=reply_thread,
        source_channel="slack_auto_reply",
    )


async def handle_inbound_slack(
    event: dict,
    *,
    event_type: str = "message",
    event_id: str = "",
    say=None,
) -> dict:
    """Route Slack DM or @mention to the coordinator and post a reply."""
    if not mark_inbound_seen(
        event_id=event_id,
        channel_id=str(event.get("channel") or ""),
        message_ts=str(event.get("ts") or ""),
    ):
        return {"handled": 0, "duplicate": True, "event_id": event_id}

    touch_event()

    if event.get("bot_id") or event.get("subtype"):
        return {"handled": 0, "skipped": "bot_or_subtype"}

    user_id = str(event.get("user") or "")
    channel_id = str(event.get("channel") or "")
    message_ts = str(event.get("ts") or "")
    thread_ts = str(event.get("thread_ts") or message_ts)
    is_dm = is_dm_event(event)
    conv_key = conversation_thread_key(channel_id=channel_id, thread_ts=thread_ts, is_dm=is_dm)
    text = _normalize_text(str(event.get("text") or ""), event_type=event_type)

    if not user_id or not channel_id or not text:
        return {"handled": 0, "skipped": "empty"}

    if message_ts and has_assistant_reply_for(message_ts):
        return {"handled": 0, "duplicate": True, "message_id": message_ts}

    reply_thread = reply_thread_ts(event, event_type=event_type)
    slack_privileged = is_privileged_slack_user(user_id)

    _schedule_ingest(event, user_id=user_id, channel_id=channel_id)

    from tempa.channels.jira.tickets import handle_jira_ticket_message, should_route_to_jira_ticket, ticket_feature_enabled
    from tempa.channels.slack.varys_bridge import enrich_slack_context

    slack_ctx = enrich_slack_context(event, {"slack_privileged": slack_privileged})
    if ticket_feature_enabled() and should_route_to_jira_ticket(text, slack_ctx):
        ticket_reply = await handle_jira_ticket_message(text, slack_ctx)
        if ticket_reply:
            await _post_slack_reply(channel_id, ticket_reply, reply_thread=reply_thread, say=say)
            record_conversation_turn(
                role="user",
                text=text,
                user_id=user_id,
                channel_id=channel_id,
                message_id=message_ts,
                thread_ts=thread_ts,
                conversation_key=conv_key,
            )
            record_conversation_turn(
                role="assistant",
                text=ticket_reply,
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=reply_thread,
                conversation_key=conv_key,
            )
            return {
                "handled": 1,
                "reply": ticket_reply,
                "skipped_coordinator": True,
                "user": user_id,
                "channel": channel_id,
                "jira_ticket": True,
            }

    if not slack_privileged:
        from tempa.agents.intent import wants_private_integrations

        if wants_private_integrations(text):
            reply = GUEST_PRIVATE_COMING_SOON
            await _post_slack_reply(channel_id, reply, reply_thread=reply_thread, say=say)
            record_conversation_turn(
                role="user",
                text=text,
                user_id=user_id,
                channel_id=channel_id,
                message_id=message_ts,
                thread_ts=thread_ts,
                conversation_key=conv_key,
            )
            record_conversation_turn(
                role="assistant",
                text=reply,
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=reply_thread,
                conversation_key=conv_key,
            )
            return {
                "handled": 1,
                "reply": reply,
                "skipped_coordinator": True,
                "user": user_id,
                "channel": channel_id,
            }

    record_conversation_turn(
        role="user",
        text=text,
        user_id=user_id,
        channel_id=channel_id,
        message_id=message_ts,
        thread_ts=thread_ts,
        conversation_key=conv_key,
    )

    try:
        from tempa.agents.graph import run_coordinator_full

        full = await run_coordinator_full(
            text,
            slack_ctx,
        )
        reply = str(full.get("response") or "").strip()
    except Exception as exc:
        logger.exception("Slack reply failed")
        err = str(exc)
        if "No Claude runner" in err or "Claude Code CLI failed" in err:
            reply = ERROR_CLAUDE_RUNNER
        else:
            reply = ERROR_GENERIC
        set_error(err[:200])

    if not reply:
        reply = ERROR_EMPTY_REPLY

    try:
        send_result = await _post_slack_reply(
            channel_id, reply, reply_thread=reply_thread, say=say
        )
    except Exception:
        logger.exception("Slack outbound reply failed")
        send_result = await _post_slack_reply(
            channel_id, reply, reply_thread=reply_thread, say=None
        )

    record_conversation_turn(
        role="assistant",
        text=reply,
        user_id=user_id,
        channel_id=channel_id,
        thread_ts=reply_thread,
        conversation_key=conv_key,
    )
    await event_bus.publish_json("channel", "slack_reply", user_id)
    set_error(None)
    return {
        "handled": 1,
        "reply": reply,
        "send": send_result,
        "user": user_id,
        "channel": channel_id,
    }
