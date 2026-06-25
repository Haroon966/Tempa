from __future__ import annotations

import asyncio
import logging
import re

from tempa.channels.slack.conversation import has_assistant_reply_for, record_conversation_turn
from tempa.channels.slack.ingest import ingest_slack_message
from tempa.channels.slack.outbound import send_slack_message
from tempa.channels.slack.session import mark_event_seen, set_error, touch_event
from tempa.channels.slack.users import (
    GUEST_PRIVATE_COMING_SOON,
    is_privileged_slack_user,
)
from tempa.core.events import event_bus

logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")


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


async def handle_inbound_slack(
    event: dict,
    *,
    event_type: str = "message",
    event_id: str = "",
    say=None,
) -> dict:
    """Route Slack DM or @mention to the coordinator and post a reply."""
    if not mark_event_seen(event_id):
        return {"handled": 0, "duplicate": True, "event_id": event_id}

    touch_event()

    if event.get("bot_id") or event.get("subtype"):
        return {"handled": 0, "skipped": "bot_or_subtype"}

    user_id = str(event.get("user") or "")
    channel_id = str(event.get("channel") or "")
    message_ts = str(event.get("ts") or "")
    thread_ts = str(event.get("thread_ts") or message_ts)
    text = _normalize_text(str(event.get("text") or ""), event_type=event_type)

    if not user_id or not channel_id or not text:
        return {"handled": 0, "skipped": "empty"}

    if message_ts and has_assistant_reply_for(message_ts):
        return {"handled": 0, "duplicate": True, "message_id": message_ts}

    is_dm = event.get("channel_type") == "im" or channel_id.startswith("D")
    is_mention = event_type == "app_mention"
    in_assistant_thread = bool(event.get("thread_ts")) and is_dm and not is_mention
    slack_privileged = is_privileged_slack_user(user_id)

    asyncio.create_task(
        asyncio.to_thread(_ingest_inbound, event, user_id=user_id, channel_id=channel_id)
    )

    if not slack_privileged:
        from tempa.agents.intent import wants_private_integrations

        if wants_private_integrations(text):
            reply = GUEST_PRIVATE_COMING_SOON
            reply_thread = thread_ts if (is_mention or in_assistant_thread) else ""
            if say is not None:
                kwargs = {"text": reply}
                if reply_thread:
                    kwargs["thread_ts"] = reply_thread
                await say(**kwargs)
            else:
                await send_slack_message(
                    channel_id,
                    reply,
                    thread_ts=reply_thread,
                    source_channel="slack_auto_reply",
                )
            record_conversation_turn(
                role="user",
                text=text,
                user_id=user_id,
                channel_id=channel_id,
                message_id=message_ts,
                thread_ts=thread_ts,
            )
            record_conversation_turn(
                role="assistant",
                text=reply,
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=reply_thread,
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
    )

    try:
        from tempa.agents.graph import run_coordinator_full
        from tempa.channels.slack.varys_bridge import enrich_slack_context

        full = await run_coordinator_full(
            text,
            enrich_slack_context(
                event,
                {
                    "slack_privileged": slack_privileged,
                },
            ),
        )
        reply = str(full.get("response") or "").strip()
    except Exception as exc:
        logger.exception("Slack reply failed")
        reply = f"Tempa encountered an error: {exc}"
        set_error(str(exc)[:200])

    if not reply:
        reply = "I'm here — I couldn't generate a reply just now."

    reply_thread = thread_ts if (is_mention or in_assistant_thread) else ""
    try:
        if say is not None:
            kwargs = {"text": reply}
            if reply_thread:
                kwargs["thread_ts"] = reply_thread
            await say(**kwargs)
            send_result = {"status": "sent", "via": "say"}
        else:
            send_result = await send_slack_message(
                channel_id,
                reply,
                thread_ts=reply_thread,
                source_channel="slack_auto_reply",
            )
    except Exception as exc:
        logger.exception("Slack outbound reply failed")
        send_result = await send_slack_message(
            channel_id,
            reply,
            thread_ts=reply_thread,
            source_channel="slack_auto_reply",
        )

    record_conversation_turn(
        role="assistant",
        text=reply,
        user_id=user_id,
        channel_id=channel_id,
        thread_ts=reply_thread,
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
