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


def list_thread_messages(
    *,
    channel_id: str = "",
    thread_ts: str = "",
    conversation_key: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Read Slack conversation turns from disk for dashboard session detail.

    Unlike get_recent_messages (in-memory deque, maxlen 100), this scans the
    jsonl history so older thread turns stay visible.
    """
    path = _history_path()
    if not path.exists():
        return []
    key = (conversation_key or thread_ts or "").strip()
    ch = (channel_id or "").strip()
    matched: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or not row.get("text"):
                continue
            if ch and str(row.get("channel_id") or "") != ch:
                continue
            if key and not _matches_conversation(row, key):
                continue
            matched.append(row)
    except Exception:
        return []
    return matched[-max(1, limit) :]


def thread_key(*, channel_id: str = "", thread_ts: str = "") -> str:
    ch = (channel_id or "").strip()
    ts = (thread_ts or "").strip()
    if ch and ts:
        return f"{ch}:{ts}"
    return ts or ch


def participants_for_threads(
    threads: list[tuple[str, str]],
) -> dict[str, list[str]]:
    """One jsonl scan → {channel:thread_ts → ordered unique human user ids}.

    Assistant/bot turns are skipped. Order is first appearance in the file.
    """
    wanted = {
        thread_key(channel_id=ch, thread_ts=ts)
        for ch, ts in threads
        if (ch or "").strip() or (ts or "").strip()
    }
    if not wanted:
        return {}
    path = _history_path()
    if not path.exists():
        return {}
    out: dict[str, list[str]] = {k: [] for k in wanted}
    seen: dict[str, set[str]] = {k: set() for k in wanted}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            if str(row.get("role") or "") == "assistant":
                continue
            uid = str(row.get("user_id") or "").strip()
            if not uid:
                continue
            ch = str(row.get("channel_id") or "").strip()
            ts = str(row.get("thread_ts") or row.get("conversation_key") or "").strip()
            key = thread_key(channel_id=ch, thread_ts=ts)
            if key not in wanted:
                # DM rows may key by channel only
                if ch and ch in wanted:
                    key = ch
                else:
                    continue
            if uid in seen[key]:
                continue
            seen[key].add(uid)
            out[key].append(uid)
    except Exception:
        return out
    return out


def participants_from_turns(
    turns: list[dict[str, Any]],
    *,
    starter_user_id: str = "",
) -> list[str]:
    """Ordered unique humans from turns, starter first when known."""
    ordered: list[str] = []
    seen: set[str] = set()
    starter = (starter_user_id or "").strip()
    if starter:
        ordered.append(starter)
        seen.add(starter)
    for turn in turns:
        if str(turn.get("role") or "") == "assistant":
            continue
        uid = str(turn.get("user_id") or "").strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        ordered.append(uid)
    return ordered


def bot_participated_in_thread(channel_id: str, thread_ts: str) -> bool:
    """True when Tempa already replied in this Slack thread or DM.

    Sources (any one is enough):
    1. In-memory conversation turns
    2. Disk conversation.jsonl (Cursor sync posts land here)
    3. A Cursor job already bound to this channel+thread
    """
    if not channel_id or not thread_ts:
        return False
    msgs = get_recent_messages(limit=100, channel_id=channel_id, conversation_key=thread_ts)
    if any(m.get("role") == "assistant" for m in msgs):
        return True
    try:
        disk = list_thread_messages(channel_id=channel_id, thread_ts=thread_ts, limit=50)
        if any(m.get("role") == "assistant" for m in disk):
            return True
    except Exception:
        pass
    try:
        from tempa.channels.slack.cursor_jobs import thread_has_cursor_job

        if thread_has_cursor_job(channel_id=channel_id, thread_ts=thread_ts):
            return True
    except Exception:
        pass
    return False


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

    # Permanent: keep Cursor job participant_ids in sync with everyone who speaks.
    if role == "user" and user_id and channel_id and thread_ts:
        try:
            from tempa.channels.slack.cursor_jobs import add_thread_participants
            from tempa.channels.slack.profiles import remember_profile

            add_thread_participants(
                channel_id=channel_id,
                thread_ts=thread_ts,
                user_ids=[user_id],
            )
            remember_profile(user_id)
        except Exception:
            pass
