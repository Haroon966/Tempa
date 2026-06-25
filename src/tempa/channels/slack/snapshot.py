from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.channels.slack.client import (
    iter_conversation_messages,
    list_conversations,
    load_slack_client,
    user_display_name,
)
from tempa.channels.slack.session import slack_configured
from tempa.settings import get_settings

logger = logging.getLogger(__name__)


def _snapshot_path() -> Path:
    path = get_settings().sessions_dir / "slack" / "snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_slack_snapshot() -> dict[str, Any]:
    path = _snapshot_path()
    if not path.exists():
        return {"channels": [], "recent_messages": [], "last_sync_at": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"channels": [], "recent_messages": [], "last_sync_at": ""}


def save_slack_snapshot(data: dict[str, Any]) -> None:
    _snapshot_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _channel_label(channel: dict[str, Any], user_names: dict[str, str]) -> str:
    if channel.get("is_im"):
        user_id = str(channel.get("user") or "")
        return user_names.get(user_id, f"DM {user_id}")
    return channel.get("name") or str(channel.get("id") or "channel")


def _message_row(
    msg: dict[str, Any],
    *,
    channel_id: str,
    channel_name: str,
    user_names: dict[str, str],
) -> dict[str, Any]:
    user_id = str(msg.get("user") or "")
    return {
        "channel_id": channel_id,
        "channel": channel_name,
        "user": user_names.get(user_id, user_id),
        "text": str(msg.get("text") or "")[:400],
        "ts": str(msg.get("ts") or ""),
        "thread_ts": str(msg.get("thread_ts") or ""),
    }


def refresh_slack_snapshot(
    *,
    client=None,
    channels: list[dict[str, Any]] | None = None,
    user_names: dict[str, str] | None = None,
    per_channel: int = 5,
    max_channels: int = 20,
) -> dict[str, Any]:
    if not slack_configured():
        return {"status": "skipped", "reason": "Slack not configured"}

    client = client or load_slack_client()
    if client is None:
        return {"status": "skipped", "reason": "Slack not configured"}

    names = dict(user_names or {})
    channel_rows: list[dict[str, Any]] = []
    recent: list[dict[str, Any]] = []

    try:
        channels = channels or list_conversations(client)
    except Exception:
        logger.exception("Slack snapshot channel list failed")
        return {"status": "error", "reason": "conversations_list failed"}

    for channel in channels[:max_channels]:
        channel_id = str(channel.get("id") or "")
        if not channel_id:
            continue
        label = _channel_label(channel, names)
        channel_rows.append(
            {
                "id": channel_id,
                "name": label,
                "is_im": bool(channel.get("is_im")),
                "is_private": bool(channel.get("is_private")),
            }
        )
        try:
            for msg in iter_conversation_messages(client, channel_id, limit=per_channel):
                if msg.get("bot_id") or msg.get("subtype"):
                    continue
                recent.append(
                    _message_row(msg, channel_id=channel_id, channel_name=label, user_names=names)
                )
        except Exception:
            logger.debug("Slack snapshot history failed for %s", channel_id, exc_info=True)

    recent.sort(key=lambda row: float(row.get("ts") or 0), reverse=True)
    snapshot = {
        "last_sync_at": datetime.now(timezone.utc).isoformat(),
        "channels": channel_rows,
        "recent_messages": recent[:50],
        "channel_count": len(channel_rows),
    }
    save_slack_snapshot(snapshot)
    return {
        "status": "ok",
        "channels": len(channel_rows),
        "recent_messages": len(snapshot["recent_messages"]),
    }
