from __future__ import annotations

import json
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any

from tempa.settings import get_settings

_recent_messages: deque[dict[str, Any]] = deque(maxlen=100)
_loaded = False


def _history_path() -> Path:
    settings = get_settings()
    path = settings.sessions_dir / "whatsapp" / "conversation.jsonl"
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


def has_assistant_reply_for(message_id: str) -> bool:
    """True when this inbound message already has an assistant reply recorded."""
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


def get_recent_messages(limit: int = 20) -> list[dict[str, Any]]:
    _load_history()
    return list(_recent_messages)[-limit:]


def record_conversation_turn(
    *,
    role: str,
    text: str,
    from_number: str = "",
    message_id: str = "",
    chat_id: str = "",
) -> None:
    if not text.strip():
        return
    _load_history()
    row = {
        "role": role,
        "from": from_number,
        "text": text,
        "id": message_id,
        "chat_id": chat_id,
    }
    _recent_messages.append(row)
    try:
        with _history_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass
