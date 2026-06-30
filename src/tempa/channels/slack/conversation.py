from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.settings import get_settings

_recent_messages: deque[dict[str, Any]] = deque(maxlen=100)
_loaded = False


def conversation_thread_key(*, channel_id: str, thread_ts: str, is_dm: bool) -> str:
    """Stable key for grouping turns — one DM channel = one conversation."""
    if is_dm and channel_id:
        return channel_id
    return thread_ts or channel_id


def _history_path() -> Path:
    settings = get_settings()
    path = settings.sessions_dir / "slack" / "conversation.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_history() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    path = _history_path()
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if isinstance(row, dict) and row.get("text"):
                _recent_messages.append(row)
    except Exception:
        pass


def _matches_conversation(row: dict[str, Any], conversation_key: str) -> bool:
    if not conversation_key:
        return True
    if row.get("conversation_key") == conversation_key:
        return True
    # Legacy rows without conversation_key
    if row.get("conversation_key"):
        return False
    ts = str(row.get("thread_ts") or "")
    if not ts:
        return True
    if ts == conversation_key or row.get("id") == conversation_key:
        return True
    return False


def get_recent_messages(
    limit: int = 20,
    *,
    user_id: str = "",
    channel_id: str = "",
    thread_ts: str = "",
    conversation_key: str = "",
) -> list[dict[str, Any]]:
    _load_history()
    key = conversation_key or thread_ts
    msgs = list(_recent_messages)
    if channel_id:
        msgs = [m for m in msgs if m.get("channel_id") == channel_id]
    if key:
        msgs = [m for m in msgs if _matches_conversation(m, key)]
    if user_id:
        msgs = [m for m in msgs if m.get("user_id") == user_id or m.get("role") == "assistant"]
    return msgs[-limit:]


def bot_participated_in_thread(channel_id: str, thread_ts: str) -> bool:
    """True when Tempa already replied in this Slack thread or DM."""
    if not channel_id or not thread_ts:
        return False
    msgs = get_recent_messages(limit=100, channel_id=channel_id, conversation_key=thread_ts)
    return any(m.get("role") == "assistant" for m in msgs)


def has_assistant_reply_for(message_id: str) -> bool:
    if not message_id:
        return False
    _load_history()
    msgs = list(_recent_messages)
    user_idx: int | None = None
    for i, row in enumerate(msgs):
        if row.get("role") == "user" and row.get("id") == message_id:
            user_idx = i
            break
    if user_idx is None:
        return False
    for row in msgs[user_idx + 1 : user_idx + 8]:
        if row.get("role") == "user":
            return False
        if row.get("role") == "assistant":
            return True
    return False


def record_conversation_turn(
    *,
    role: str,
    text: str,
    user_id: str = "",
    channel_id: str = "",
    message_id: str = "",
    thread_ts: str = "",
    conversation_key: str = "",
) -> None:
    if not text.strip():
        return
    _load_history()
    row = {
        "role": role,
        "user_id": user_id,
        "channel_id": channel_id,
        "text": text,
        "id": message_id,
        "thread_ts": thread_ts,
        "conversation_key": conversation_key,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _recent_messages.append(row)
    try:
        with _history_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass
