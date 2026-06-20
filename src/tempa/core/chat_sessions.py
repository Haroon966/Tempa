from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from tempa.settings import get_settings

MessageRole = Literal["user", "assistant"]

_lock = threading.Lock()


def _chat_dir() -> Any:
    path = get_settings().sessions_dir / "chat"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path() -> Any:
    return _chat_dir() / "index.json"


def _session_path(session_id: str) -> Any:
    sessions = _chat_dir() / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    return sessions / f"{session_id}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_index_unlocked() -> list[dict[str, Any]]:
    path = _index_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_index_unlocked(entries: list[dict[str, Any]]) -> None:
    _index_path().write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_session_unlocked(session_id: str) -> dict[str, Any] | None:
    path = _session_path(session_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_session_unlocked(session: dict[str, Any]) -> None:
    _session_path(session["id"]).write_text(
        json.dumps(session, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _truncate_title(text: str, limit: int = 60) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned or "New chat"
    return cleaned[: limit - 1].rstrip() + "…"


def list_sessions() -> list[dict[str, Any]]:
    with _lock:
        entries = _read_index_unlocked()
    return sorted(entries, key=lambda e: e.get("updated_at", ""), reverse=True)


def get_session(session_id: str) -> dict[str, Any] | None:
    with _lock:
        return _read_session_unlocked(session_id)


def create_session(title: str = "") -> dict[str, Any]:
    session_id = str(uuid.uuid4())
    now = _now_iso()
    session = {
        "id": session_id,
        "title": title or "New chat",
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }
    with _lock:
        _write_session_unlocked(session)
        entries = _read_index_unlocked()
        entries.append(
            {
                "id": session_id,
                "title": session["title"],
                "created_at": now,
                "updated_at": now,
            }
        )
        _write_index_unlocked(entries)
    return session


def update_title(session_id: str, title: str) -> dict[str, Any] | None:
    with _lock:
        session = _read_session_unlocked(session_id)
        if not session:
            return None
        session["title"] = title
        session["updated_at"] = _now_iso()
        _write_session_unlocked(session)
        entries = _read_index_unlocked()
        for entry in entries:
            if entry.get("id") == session_id:
                entry["title"] = title
                entry["updated_at"] = session["updated_at"]
                break
        _write_index_unlocked(entries)
    return session


def append_message(
    session_id: str,
    role: MessageRole,
    content: str,
    sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    with _lock:
        session = _read_session_unlocked(session_id)
        if not session:
            return None
        now = _now_iso()
        message = {
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "sources": sources or [],
            "created_at": now,
        }
        session["messages"].append(message)
        session["updated_at"] = now
        if role == "user" and (session.get("title") in ("", "New chat") or not session.get("title")):
            session["title"] = _truncate_title(content)
        _write_session_unlocked(session)
        entries = _read_index_unlocked()
        for entry in entries:
            if entry.get("id") == session_id:
                entry["title"] = session["title"]
                entry["updated_at"] = now
                break
        _write_index_unlocked(entries)
    return message


def delete_session(session_id: str) -> bool:
    with _lock:
        session = _read_session_unlocked(session_id)
        if not session:
            return False
        path = _session_path(session_id)
        if path.exists():
            path.unlink()
        entries = [e for e in _read_index_unlocked() if e.get("id") != session_id]
        _write_index_unlocked(entries)
    return True


def ensure_session(session_id: str | None) -> dict[str, Any]:
    if session_id:
        session = get_session(session_id)
        if session:
            return session
    return create_session()


def session_count() -> int:
    with _lock:
        return len(_read_index_unlocked())
