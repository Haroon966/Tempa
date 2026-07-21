"""Sync #presence Slack channel into local status store."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from tempa.channels.slack.client import (
    iter_conversation_messages,
    list_users,
    load_slack_client,
    user_display_name,
)
from tempa.channels.slack.presence_llm import classify_presence
from tempa.channels.slack.presence_parse import (
    classify_presence_text,
    dates_for_classification,
    presence_tz,
    today_in_tz,
)
from tempa.channels.slack.presence_store import (
    build_payload,
    has_seen_message,
    load_sync_state,
    save_members,
    save_sync_state,
    upsert_presence,
)
from tempa.channels.slack.session import slack_configured
from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_SKIP_SUBTYPES = frozenset(
    {"channel_join", "channel_leave", "group_join", "group_leave", "pinned_item", "message_deleted"}
)


def _should_skip(msg: dict[str, Any]) -> bool:
    if msg.get("bot_id"):
        return True
    subtype = str(msg.get("subtype") or "")
    if subtype and subtype not in {"thread_broadcast", "file_share"}:
        if subtype in _SKIP_SUBTYPES or subtype.startswith("channel_"):
            return True
        # ignore most subtypes; allow plain + thread_broadcast
        if subtype not in {"thread_broadcast"}:
            return True
    if not str(msg.get("user") or "").strip():
        return True
    if not str(msg.get("text") or "").strip():
        return True
    return False


def _ts_to_iso(ts: str) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc).isoformat()


def _user_names(client) -> tuple[dict[str, str], dict[str, str], dict[str, str], set[str]]:
    """Return (id -> display name, id -> avatar URL, id -> email, ids of bots/deleted users)."""
    try:
        users = list_users(client)
    except Exception:
        logger.exception("Presence sync users.list failed")
        return {}, {}, {}, set()
    names: dict[str, str] = {}
    images: dict[str, str] = {}
    emails: dict[str, str] = {}
    excluded: set[str] = set()
    for user in users:
        uid = str(user.get("id") or "")
        if not uid:
            continue
        names[uid] = user_display_name(user)
        profile = user.get("profile") or {}
        image = str(profile.get("image_192") or profile.get("image_72") or "")
        if image:
            images[uid] = image
        # requires the users:read.email scope; empty otherwise
        email = str(profile.get("email") or "")
        if email:
            emails[uid] = email
        if user.get("is_bot") or user.get("deleted") or uid == "USLACKBOT":
            excluded.add(uid)
    return names, images, emails, excluded


def _refresh_members(
    client,
    channel_id: str,
    names: dict[str, str],
    images: dict[str, str],
    emails: dict[str, str],
    excluded: set[str],
) -> int:
    """Fetch #presence channel members and persist the human roster."""
    member_ids: list[str] = []
    cursor = None
    try:
        while True:
            kwargs: dict[str, Any] = {"channel": channel_id, "limit": 200}
            if cursor:
                kwargs["cursor"] = cursor
            response = client.conversations_members(**kwargs)
            member_ids.extend(str(m) for m in (response.get("members") or []))
            cursor = (response.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
    except Exception:
        logger.exception("Presence conversations.members failed")
        return 0
    roster = [
        {
            "user_id": uid,
            "name": names.get(uid) or uid,
            "image": images.get(uid, ""),
            "email": emails.get(uid, ""),
        }
        for uid in member_ids
        if uid and uid not in excluded
    ]
    save_members(roster)
    return len(roster)


def sync_presence_once(*, backfill_days: int = 7, limit: int = 400) -> dict[str, Any]:
    if not slack_configured():
        return {"status": "skipped", "reason": "Slack not configured"}

    settings = get_settings()
    channel_id = (settings.slack_presence_channel_id or "").strip()
    if not channel_id:
        return {"status": "skipped", "reason": "presence channel not configured"}

    client = load_slack_client()
    if client is None:
        return {"status": "skipped", "reason": "Slack not configured"}

    state = load_sync_state()
    oldest = ""
    if not state.get("latest_ts"):
        oldest_dt = datetime.now(presence_tz()) - timedelta(days=max(1, backfill_days))
        oldest = str(oldest_dt.timestamp())
    else:
        # slight overlap to avoid gaps
        try:
            oldest = str(float(state["latest_ts"]) - 1)
        except (TypeError, ValueError):
            oldest = ""

    names, images, emails, excluded = _user_names(client)
    roster_size = _refresh_members(client, channel_id, names, images, emails, excluded)
    classified = 0
    skipped_seen = 0
    errors = 0
    max_ts = str(state.get("latest_ts") or "")

    try:
        messages = list(
            iter_conversation_messages(client, channel_id, oldest=oldest, limit=limit)
        )
    except Exception as exc:
        logger.exception("Presence conversations.history failed")
        return {"status": "error", "reason": str(exc)}

    # history returns newest-first; process oldest-first so latest wins correctly
    messages.sort(key=lambda m: str(m.get("ts") or ""))

    for msg in messages:
        if _should_skip(msg):
            continue
        message_ts = str(msg.get("ts") or "")
        if not message_ts:
            continue
        if max_ts and message_ts > max_ts:
            max_ts = message_ts
        elif not max_ts:
            max_ts = message_ts

        if has_seen_message(message_ts, state=state):
            skipped_seen += 1
            continue

        user_id = str(msg.get("user") or "")
        text = str(msg.get("text") or "")
        try:
            msg_day = today_in_tz()
            try:
                msg_day = datetime.fromtimestamp(float(message_ts), tz=presence_tz()).date()
            except (TypeError, ValueError, OSError):
                pass
            # ponytail: LLM only for today/tomorrow — older backfill uses rules (cheap)
            today = today_in_tz()
            if msg_day >= today:
                classification = classify_presence(text, message_ts=message_ts)
            else:
                classification = classify_presence_text(text, message_ts=message_ts)
            for day in dates_for_classification(classification):
                upsert_presence(
                    day=day,
                    user_id=user_id,
                    display_name=names.get(user_id) or user_id,
                    classification=classification,
                    message_ts=message_ts,
                    ts_iso=_ts_to_iso(message_ts),
                )
            classified += 1
            seen = list(state.get("seen_message_ts") or [])
            if message_ts not in seen:
                seen.append(message_ts)
            state["seen_message_ts"] = seen
        except Exception:
            logger.exception("Presence classify failed for ts=%s", message_ts)
            errors += 1
            # still mark seen to avoid infinite retry burn? keep unmarked so retry works
            continue

    state["latest_ts"] = max_ts or state.get("latest_ts") or ""
    state["last_sync_at"] = datetime.now(timezone.utc).isoformat()
    save_sync_state(state)

    return {
        "status": "ok",
        "classified": classified,
        "skipped_seen": skipped_seen,
        "errors": errors,
        "roster_size": roster_size,
        "channel_id": channel_id,
        "latest_ts": state["latest_ts"],
    }


async def sync_presence_async(**kwargs: Any) -> dict[str, Any]:
    import asyncio

    return await asyncio.to_thread(sync_presence_once, **kwargs)


def get_presence_payload(day: str | None = None) -> dict[str, Any]:
    return build_payload(day)
