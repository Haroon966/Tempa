from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from tempa.channels.slack.conversation import record_conversation_turn
from tempa.channels.slack.formatting import prepare_slack_reply
from tempa.channels.slack.session import set_error, slack_configured
from tempa.core.events import event_bus
from tempa.rag.ingest import ingest_text
from tempa.router.safety import screen_outbound_message

logger = logging.getLogger(__name__)

_SLACK_TEXT_LIMIT = 3900


def _split_text(text: str, limit: int = _SLACK_TEXT_LIMIT) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(text[:split_at].rstrip())
        text = text[split_at:].lstrip()
    return chunks


async def _get_client():
    from tempa.channels.slack.bolt_app import get_slack_web_client

    client = get_slack_web_client()
    if client is None:
        from slack_sdk.web.async_client import AsyncWebClient

        from tempa.settings import get_settings

        settings = get_settings()
        client = AsyncWebClient(token=settings.slack_bot_token)
    return client


async def send_slack_message(
    channel: str,
    text: str,
    *,
    thread_ts: str = "",
    skip_safety: bool = False,
    require_user_confirmation: bool | None = None,
    source_channel: str = "coordinator",
) -> dict[str, Any]:
    if not channel or not text.strip():
        return {"status": "error", "reason": "channel and text required"}
    if not slack_configured():
        return {"status": "disconnected", "reason": "Slack not configured"}

    auto_reply = source_channel in ("slack_auto_reply", "slack", "slack_owner_send")
    if require_user_confirmation is None:
        require_user_confirmation = source_channel not in ("slack_auto_reply", "slack", "slack_owner_send")
    if auto_reply:
        skip_safety = True

    if require_user_confirmation and not skip_safety:
        from tempa.core.notifications import notify
        from tempa.core.pending_actions import create_pending_action

        action = create_pending_action(
            "slack_send",
            {"channel": channel, "text": text, "thread_ts": thread_ts},
            source_channel=source_channel,
            risk_level="high",
            title=f"Slack message to {channel}",
        )
        await notify(
            "pending_action",
            title="Slack message needs approval",
            body=text[:120],
            pending_action_id=action["id"],
        )
        return {
            "status": "pending",
            "pending_action_id": action["id"],
            "reason": "Awaiting user confirmation",
        }

    if skip_safety:
        allowed, reason = True, "skipped"
    else:
        allowed, reason = await asyncio.to_thread(screen_outbound_message, text)
    if not allowed:
        await event_bus.publish_json("channel", "blocked", reason[:120])
        return {"status": "blocked", "reason": reason}

    formatted = prepare_slack_reply(text)
    client = await _get_client()
    chunks = _split_text(formatted)
    last: dict[str, Any] = {}
    try:
        for chunk in chunks:
            kwargs: dict[str, Any] = {"channel": channel, "text": chunk, "mrkdwn": True}
            if thread_ts:
                kwargs["thread_ts"] = thread_ts
            response = await client.chat_postMessage(**kwargs)
            last = response.data if hasattr(response, "data") else dict(response)
        record_conversation_turn(
            role="assistant",
            text=text,
            channel_id=channel,
            thread_ts=thread_ts,
        )
        if not auto_reply:
            threading.Thread(
                target=ingest_text,
                kwargs={
                    "text": text,
                    "tool": "slack",
                    "source": channel,
                    "participants": [channel],
                    "tags": ["outbound"],
                },
                daemon=True,
            ).start()
        await event_bus.publish_json("channel", "slack_sent", channel)
        set_error(None)
        return {"status": "sent", "result": last}
    except Exception as exc:
        logger.exception("Slack send failed")
        set_error(str(exc)[:200])
        return {"status": "error", "reason": str(exc)}


async def open_dm_for_user(user_id: str) -> str:
    import asyncio

    from tempa.channels.slack.client import find_dm_channel, load_slack_client, open_dm_channel

    client = await _get_client()
    sync_client = load_slack_client()

    if sync_client is not None:
        existing = await asyncio.to_thread(find_dm_channel, sync_client, user_id)
        if existing:
            return existing

    if client is not None and hasattr(client, "conversations_open"):
        try:
            response = await client.conversations_open(users=user_id)
            data = response.data if hasattr(response, "data") else dict(response)
            channel_id = str((data.get("channel") or {}).get("id") or "")
            if channel_id:
                return channel_id
        except Exception as exc:
            err = str(exc)
            if sync_client is not None:
                try:
                    return await asyncio.to_thread(open_dm_channel, sync_client, user_id)
                except Exception:
                    if "missing_scope" in err:
                        raise ValueError(
                            "No existing DM with that user. Add im:write scope to the Slack app and reinstall."
                        ) from exc
                    raise
            if "missing_scope" in err:
                raise ValueError(
                    "No existing DM with that user. Add im:write scope to the Slack app and reinstall."
                ) from exc
            raise

    if sync_client is None:
        raise ValueError("Slack not configured")
    return await asyncio.to_thread(open_dm_channel, sync_client, user_id)
