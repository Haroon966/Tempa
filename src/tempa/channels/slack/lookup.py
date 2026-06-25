from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from tempa.channels.slack.client import (
    find_dm_channel,
    iter_conversation_messages,
    list_conversations,
    list_users,
    load_slack_client,
    user_display_name,
)
from tempa.channels.slack.recipients import resolve_slack_recipient
from tempa.channels.slack.snapshot import load_slack_snapshot

logger = logging.getLogger(__name__)

_READ_INTENT_RE = re.compile(
    r"\b(?:check|read|show|get|what(?:'s| is)|tell me|latest|last)\b.*\bmessage",
    re.I,
)
_CHANNEL_IN_RE = re.compile(r"\bin\s+([#@]?[\w-]+)\s+channel\b", re.I)
_HASH_CHANNEL_RE = re.compile(r"#\s*([\w-]+)")
_USER_FROM_RE = re.compile(
    r"\b(?:message\s+)?(?:from|by|of)\s+([A-Za-z][\w.-]*)",
    re.I,
)
_INVITE_HELP_RE = re.compile(
    r"\b(?:how\s+(?:to|do\s+i)|add\s+you|invite\s+you|join\s+)(?:\s+\w+){0,4}\s*(?:channel|slack)\b",
    re.I,
)


def wants_slack_invite_help(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    return bool(_INVITE_HELP_RE.search(cleaned) or re.search(r"\badd\s+(?:tempa|you|bot)\b.*\bchannel\b", cleaned, re.I))


def slack_invite_help_text() -> str:
    return (
        "To add Tempa to a Slack channel:\n"
        "1. Open the channel in Slack.\n"
        "2. Run `/invite @Tempa` (or channel name → Integrations → Add apps → Tempa).\n"
        "3. For private channels, a channel admin must invite the app.\n"
        "4. Ask again once I'm in — e.g. *latest message from Varys in #regionpunjab-internal*."
    )


def wants_slack_read_intent(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if _READ_INTENT_RE.search(cleaned):
        return True
    if re.search(r"\b(?:latest|last)\b.*\b(?:from|by|of)\b", cleaned, re.I):
        return True
    if _HASH_CHANNEL_RE.search(cleaned) and re.search(r"\bchannel\b", cleaned, re.I):
        return True
    return False


def parse_slack_read_query(text: str) -> dict[str, str]:
    channel = ""
    match = _HASH_CHANNEL_RE.search(text)
    if match:
        channel = match.group(1).strip()
    if not channel:
        match = _CHANNEL_IN_RE.search(text)
        if match:
            channel = match.group(1).lstrip("#@")

    user = ""
    match = _USER_FROM_RE.search(text)
    if match:
        user = match.group(1).strip()
    return {"channel": channel, "user": user}


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _channel_match_score(hint: str, name: str) -> int:
    hint_raw = hint.lower().strip()
    name_raw = name.lower().strip()
    hint_key = _normalize_name(hint)
    name_key = _normalize_name(name)
    if not hint_key or not name_key:
        return 0
    if hint_key == name_key or hint_raw == name_raw:
        return 100
    if hint_raw in name_raw or name_raw in hint_raw:
        shorter = min(len(hint_key), len(name_key))
        longer = max(len(hint_key), len(name_key))
        if longer and shorter / longer >= 0.85:
            return 80
    return 0


def _name_matches(hint: str, name: str) -> bool:
    return _channel_match_score(hint, name) >= 80


def _ts_label(ts: str) -> str:
    if not ts:
        return ""
    try:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ts


def _channel_label(channel: dict[str, Any], user_names: dict[str, str]) -> str:
    if channel.get("is_im"):
        user_id = str(channel.get("user") or "")
        return user_names.get(user_id, f"DM {user_id}")
    return str(channel.get("name") or channel.get("id") or "channel")


def _iter_channels(client=None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for channel in load_slack_snapshot().get("channels") or []:
        channel_id = str(channel.get("id") or "")
        if channel_id and channel_id not in seen:
            seen.add(channel_id)
            rows.append(channel)

    client = client or load_slack_client()
    if client is None:
        return rows

    for types in ("public_channel,private_channel", "public_channel"):
        try:
            for channel in list_conversations(client, types=types, limit=500):
                channel_id = str(channel.get("id") or "")
                if channel.get("is_im") or not channel_id or channel_id in seen:
                    continue
                seen.add(channel_id)
                rows.append(channel)
        except Exception:
            logger.exception("Slack channel lookup failed for types=%s", types)
    return rows


def find_channel_by_hint(hint: str, *, client=None) -> tuple[str, str]:
    hint = (hint or "").strip().lstrip("#@")
    if not hint:
        return "", ""

    best_score = 0
    best: tuple[str, str] = ("", "")
    for channel in _iter_channels(client):
        name = str(channel.get("name") or "")
        if not name:
            continue
        score = _channel_match_score(hint, name)
        if score > best_score:
            best_score = score
            best = (str(channel.get("id") or ""), name)
    if best_score >= 80:
        return best
    return "", ""


def _build_user_names(client) -> dict[str, str]:
    names: dict[str, str] = {}
    try:
        for user in list_users(client, limit=5000):
            uid = str(user.get("id") or "")
            if uid:
                names[uid] = user_display_name(user)
    except Exception:
        logger.exception("Slack users.list failed during message lookup")
    return names


def _message_matches_user(
    msg: dict[str, Any],
    *,
    user_id: str,
    user_hint: str,
    user_names: dict[str, str],
) -> bool:
    if msg.get("bot_id") or msg.get("subtype"):
        return False
    uid = str(msg.get("user") or "")
    if not uid:
        return False
    if user_id:
        return uid == user_id
    if user_hint:
        display = user_names.get(uid, "")
        return _name_matches(user_hint, display) or _name_matches(user_hint, uid)
    return True


def lookup_latest_slack_message(text: str) -> dict[str, Any]:
    """Find the latest Slack message matching a read-style query."""
    if not wants_slack_read_intent(text):
        return {"status": "skipped"}

    query = parse_slack_read_query(text)
    client = load_slack_client()
    if client is None:
        return {"status": "error", "reason": "Slack is not configured."}

    user_hint = query["user"]
    resolved = resolve_slack_recipient(user_hint) if user_hint else {}
    user_id = str(resolved.get("user_id") or "")

    channel_id, channel_name = find_channel_by_hint(query["channel"], client=client)
    if query["channel"] and not channel_id:
        return {
            "status": "error",
            "reason": (
                f"Could not find Slack channel '{query['channel']}'. "
                "It may be private — invite Tempa with `/invite @Tempa` in that channel, "
                "and ensure the app has private-channel scopes (groups:read, groups:history)."
            ),
        }

    if not channel_id and user_id:
        channel_id = find_dm_channel(client, user_id)
        channel_name = resolved.get("name") or user_hint

    if not channel_id:
        return {
            "status": "error",
            "reason": "Tell me which channel to check, e.g. 'latest message from Varys in regionpunjab-internal channel'.",
        }

    user_names = _build_user_names(client)
    try:
        messages = list(iter_conversation_messages(client, channel_id, limit=80))
    except Exception as exc:
        err = str(exc)
        if "not_in_channel" in err:
            return {
                "status": "error",
                "reason": (
                    f"I'm not in #{channel_name} yet. Invite the Tempa app to that channel, then ask again."
                ),
            }
        return {"status": "error", "reason": f"Could not read #{channel_name}: {err}"}

    for msg in messages:
        if not _message_matches_user(
            msg,
            user_id=user_id,
            user_hint=user_hint,
            user_names=user_names,
        ):
            continue
        author = user_names.get(str(msg.get("user") or ""), user_hint or "someone")
        body = str(msg.get("text") or "").strip()
        if not body:
            continue
        return {
            "status": "ok",
            "channel": channel_name,
            "channel_id": channel_id,
            "user": author,
            "message": body,
            "timestamp": _ts_label(str(msg.get("ts") or "")),
        }

    if user_hint:
        return {
            "status": "error",
            "reason": f"No recent messages from {user_hint} in #{channel_name}.",
        }
    return {"status": "error", "reason": f"No recent messages found in #{channel_name}."}
