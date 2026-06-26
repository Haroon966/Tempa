from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from slack_sdk.errors import SlackApiError

from tempa.channels.slack.client import (
    iter_conversation_messages,
    iter_thread_replies,
    list_conversations,
    list_users,
    load_slack_client,
    user_display_name,
)
from tempa.channels.slack.ingest import ingest_slack_message
from tempa.channels.slack.session import slack_configured
from tempa.settings import get_settings

logger = logging.getLogger(__name__)


def _sync_state_path() -> Path:
    return get_settings().sessions_dir / "slack" / "sync_state.json"


def _load_config() -> dict[str, Any]:
    try:
        import yaml

        path = get_settings().config_dir / "permissions.yaml"
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("slack") or {}
    except Exception:
        return {}


def load_sync_state() -> dict[str, Any]:
    path = _sync_state_path()
    if not path.exists():
        return {"channel_cursors": {}, "seen_messages": [], "last_sync_at": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "channel_cursors": dict(data.get("channel_cursors") or {}),
            "seen_messages": list(data.get("seen_messages") or []),
            "last_sync_at": str(data.get("last_sync_at") or ""),
        }
    except Exception:
        return {"channel_cursors": {}, "seen_messages": [], "last_sync_at": ""}


def save_sync_state(state: dict[str, Any]) -> None:
    path = _sync_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _message_key(channel_id: str, ts: str) -> str:
    return f"{channel_id}:{ts}"


def _channel_name(channel: dict[str, Any]) -> str:
    if channel.get("is_im"):
        user_id = channel.get("user")
        return f"DM:{user_id}" if user_id else "DM"
    if channel.get("is_mpim"):
        return channel.get("name") or "group-dm"
    return channel.get("name") or channel.get("id") or "channel"


def _should_skip_message(msg: dict[str, Any]) -> bool:
    if msg.get("bot_id"):
        return True
    subtype = str(msg.get("subtype") or "")
    if subtype in {"channel_join", "channel_leave", "group_join", "group_leave", "pinned_item"}:
        return True
    return False


def _build_user_names(users: list[dict[str, Any]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for user in users:
        uid = str(user.get("id") or "")
        if uid:
            names[uid] = user_display_name(user)
    return names


def sync_slack_contacts_blocking() -> dict[str, Any]:
    if not slack_configured():
        return {"status": "skipped", "reason": "Slack not configured"}
    client = load_slack_client()
    if client is None:
        return {"status": "skipped", "reason": "Slack not configured"}
    try:
        users = list_users(client)
    except Exception as exc:
        logger.exception("Slack users.list failed")
        return {"status": "error", "reason": str(exc)}

    contacts: list[dict[str, Any]] = []
    for user in users:
        if user.get("deleted") or user.get("is_bot"):
            continue
        uid = str(user.get("id") or "")
        if not uid:
            continue
        profile = user.get("profile") or {}
        contacts.append(
            {
                "id": f"slack:{uid}",
                "name": user_display_name(user),
                "email": str(profile.get("email") or ""),
                "phone": str(profile.get("phone") or ""),
                "source": "slack",
            }
        )
    if not contacts:
        return {"status": "ok", "count": 0}

    from tempa.channels.contacts.store import upsert_contacts
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        count = asyncio.run(upsert_contacts(contacts))
        return {"status": "ok", "count": count}

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, upsert_contacts(contacts))
        try:
            count = future.result(timeout=45)
            return {"status": "ok", "count": count}
        except Exception as exc:
            logger.warning("Slack contact upsert failed: %s", exc)
            return {"status": "error", "reason": str(exc)}


async def sync_slack_contacts() -> dict[str, Any]:
    import asyncio

    return await asyncio.to_thread(sync_slack_contacts_blocking)


def sync_slack_once_blocking(*, full: bool = False) -> dict[str, Any]:
    if not slack_configured():
        return {"status": "skipped", "reason": "Slack not configured"}

    client = load_slack_client()
    if client is None:
        return {"status": "skipped", "reason": "Slack not configured"}

    cfg = _load_config()
    max_per_channel = int(cfg.get("max_messages_per_channel", 200))
    channel_types = cfg.get("channel_types") or [
        "im",
        "public_channel",
    ]
    types = ",".join(channel_types)

    contacts_result = sync_slack_contacts_blocking()

    try:
        users = list_users(client)
        user_names = _build_user_names(users)
        channels = list_conversations(client, types=types)
    except Exception as exc:
        logger.exception("Slack conversation/user fetch failed")
        return {"status": "error", "reason": str(exc), "contacts": contacts_result}

    state = load_sync_state()
    cursors: dict[str, str] = dict(state.get("channel_cursors") or {})
    seen = set(state.get("seen_messages") or [])
    ingested = 0
    channels_synced = 0
    threads_synced = 0

    for channel in channels:
        channel_id = str(channel.get("id") or "")
        if not channel_id:
            continue
        channel_name = _channel_name(channel)
        oldest = "" if full else str(cursors.get(channel_id) or "")
        new_latest = oldest
        channel_ingested = 0

        try:
            for msg in iter_conversation_messages(
                client,
                channel_id,
                oldest=oldest,
                limit=max_per_channel,
            ):
                if _should_skip_message(msg):
                    continue
                ts = str(msg.get("ts") or "")
                key = _message_key(channel_id, ts)
                if key in seen:
                    continue
                ingest_slack_message(
                    msg,
                    channel_id=channel_id,
                    channel_name=channel_name,
                    user_names=user_names,
                    tags=["sync"],
                )
                seen.add(key)
                ingested += 1
                channel_ingested += 1
                if not new_latest or float(ts) > float(new_latest):
                    new_latest = ts

                reply_count = int(msg.get("reply_count") or 0)
                if reply_count > 0 and ts:
                    for reply in iter_thread_replies(client, channel_id, ts, limit=reply_count + 5):
                        if _should_skip_message(reply):
                            continue
                        rts = str(reply.get("ts") or "")
                        rkey = _message_key(channel_id, rts)
                        if rkey in seen:
                            continue
                        ingest_slack_message(
                            reply,
                            channel_id=channel_id,
                            channel_name=channel_name,
                            user_names=user_names,
                            tags=["sync", "thread"],
                        )
                        seen.add(rkey)
                        ingested += 1
                        threads_synced += 1
                        if not new_latest or float(rts) > float(new_latest):
                            new_latest = rts

            if new_latest and new_latest != oldest:
                cursors[channel_id] = new_latest
            if channel_ingested or not oldest:
                channels_synced += 1
        except SlackApiError as exc:
            err = ""
            if exc.response is not None:
                err = str(exc.response.get("error") or "")
            if err == "not_in_channel":
                logger.debug("Slack sync skipped channel %s (bot not in channel)", channel_id)
            else:
                logger.exception("Slack sync failed for channel %s", channel_id)
        except Exception:
            logger.exception("Slack sync failed for channel %s", channel_id)

    state["channel_cursors"] = cursors
    state["seen_messages"] = list(seen)[-20000:]
    state["last_sync_at"] = datetime.now(timezone.utc).isoformat()
    save_sync_state(state)

    snapshot_result: dict[str, Any] = {}
    try:
        from tempa.channels.slack.snapshot import refresh_slack_snapshot

        snapshot_result = refresh_slack_snapshot(client=client, channels=channels, user_names=user_names)
    except Exception:
        logger.exception("Slack snapshot refresh failed")

    return {
        "status": "ok",
        "new_messages": ingested,
        "channels_synced": channels_synced,
        "threads_synced": threads_synced,
        "contacts": contacts_result,
        "snapshot": snapshot_result,
    }


async def sync_once(*, full: bool = False) -> dict[str, Any]:
    import asyncio

    return await asyncio.to_thread(sync_slack_once_blocking, full=full)
