from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from tempa.rag.ingest import ingest_text
from tempa.settings import get_settings

_lock = threading.Lock()

PREFERENCE_PATTERNS = [
    re.compile(r"from now on[,.]?\s*(.+)", re.I),
    re.compile(r"always\s+(.+)", re.I),
    re.compile(r"never\s+(.+)", re.I),
    re.compile(r"remember to\s+(.+)", re.I),
    re.compile(r"prefer(?:ence)?\s+(?:that\s+)?(.+)", re.I),
]


def _store_path() -> Any:
    return get_settings().sessions_dir / "memory" / "procedural.json"


def _ensure_dir() -> None:
    _store_path().parent.mkdir(parents=True, exist_ok=True)


def _read_all_unlocked() -> list[dict[str, Any]]:
    path = _store_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_all_unlocked(items: list[dict[str, Any]]) -> None:
    _ensure_dir()
    _store_path().write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def add_preference(
    rule: str,
    *,
    source: str = "manual",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    rule = rule.strip()
    if not rule:
        raise ValueError("empty rule")
    with _lock:
        items = _read_all_unlocked()
        record = {
            "id": str(uuid.uuid4()),
            "rule": rule,
            "source": source,
            "tags": tags or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        items.append(record)
        _write_all_unlocked(items)
    ingest_text(rule, tool="procedural", source=source, tags=["preference", *(tags or [])])
    return record


def list_preferences() -> list[dict[str, Any]]:
    with _lock:
        return list(_read_all_unlocked())


def delete_preference(pref_id: str) -> bool:
    with _lock:
        items = _read_all_unlocked()
        filtered = [p for p in items if p.get("id") != pref_id]
        if len(filtered) == len(items):
            return False
        _write_all_unlocked(filtered)
        return True


def format_preferences_for_prompt(limit: int = 10) -> str:
    items = list_preferences()[-limit:]
    if not items:
        return ""
    lines = [f"- {p['rule']}" for p in items]
    return "User preferences (procedural memory):\n" + "\n".join(lines)


def extract_preference_from_message(message: str) -> str | None:
    for pat in PREFERENCE_PATTERNS:
        match = pat.search(message)
        if match:
            return match.group(1).strip().rstrip(".")
    return None


def maybe_capture_from_message(message: str) -> dict[str, Any] | None:
    rule = extract_preference_from_message(message)
    if rule:
        return add_preference(rule, source="explicit", tags=["auto"])
    return None


def capture_from_approval(action_type: str, payload: dict[str, Any]) -> None:
    if action_type == "email_send":
        to = str(payload.get("to", "")).strip()
        if payload.get("body_html") and to:
            add_preference(
                f"Use HTML format for emails to {to}",
                source="approval",
                tags=["email"],
            )
        elif to:
            add_preference(
                f"User approved sending email to {to}",
                source="approval",
                tags=["email"],
            )
    elif action_type == "whatsapp_send":
        number = str(payload.get("number", "")).strip()
        if number:
            add_preference(
                f"User approved WhatsApp messages to {number}",
                source="approval",
                tags=["whatsapp"],
            )
