from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from tempa.rag.ingest import ingest_text

_USER_MENTION_RE = re.compile(r"<@([A-Z0-9]+)>")


def _ts_to_iso(ts: str) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except Exception:
        return ts


def _resolve_mentions(text: str, user_names: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        uid = match.group(1)
        name = user_names.get(uid)
        return f"@{name}" if name else match.group(0)

    return _USER_MENTION_RE.sub(repl, text or "")


def message_to_text(
    msg: dict[str, Any],
    *,
    channel_name: str = "",
    user_names: dict[str, str] | None = None,
) -> str:
    names = user_names or {}
    user_id = str(msg.get("user") or "")
    author = names.get(user_id, user_id or "unknown")
    text = _resolve_mentions(str(msg.get("text") or ""), names)
    ts = _ts_to_iso(str(msg.get("ts") or ""))
    parts = [f"Channel: {channel_name or msg.get('channel', '')}", f"From: {author}", f"Time: {ts}"]
    if msg.get("thread_ts") and msg.get("thread_ts") != msg.get("ts"):
        parts.append(f"Thread: {msg.get('thread_ts')}")
    if text:
        parts.append(text)
    return "\n".join(parts)


def ingest_slack_message(
    msg: dict[str, Any],
    *,
    channel_id: str,
    channel_name: str = "",
    user_names: dict[str, str] | None = None,
    tags: list[str] | None = None,
) -> dict:
    if msg.get("bot_id") or msg.get("subtype"):
        return {"chunks_created": 0}
    text = message_to_text(msg, channel_name=channel_name, user_names=user_names)
    if not text.strip():
        return {"chunks_created": 0}
    user_id = str(msg.get("user") or "")
    ts = str(msg.get("ts") or "")
    tag_list = list(tags or ["sync"])
    if ts:
        tag_list.append(f"msg:{ts}")
    return ingest_text(
        text,
        tool="slack",
        source=channel_id,
        participants=[user_id, channel_id],
        tags=tag_list,
        title=f"Slack {channel_name or channel_id}",
        content_date=_ts_to_iso(ts),
    )
