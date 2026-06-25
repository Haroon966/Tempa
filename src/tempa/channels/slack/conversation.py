from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.settings import get_settings

_recent_messages: deque[dict[str, Any]] = deque(maxlen=100)
_loaded = False


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


def get_recent_messages(
    limit: int = 20,
    *,
    user_id: str = "",
    channel_id: str = "",
    thread_ts: str = "",
) -> list[dict[str, Any]]:
    _load_history()
    msgs = list(_recent_messages)
    if channel_id:
        msgs = [m for m in msgs if m.get("channel_id") == channel_id]
    if thread_ts:
        msgs = [
            m
            for m in msgs
            if not m.get("thread_ts")
            or m.get("thread_ts") == thread_ts
            or m.get("id") == thread_ts
        ]
    if user_id:
        msgs = [m for m in msgs if m.get("user_id") == user_id or m.get("role") == "assistant"]
    return msgs[-limit:]


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
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _recent_messages.append(row)
    try:
        with _history_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass
