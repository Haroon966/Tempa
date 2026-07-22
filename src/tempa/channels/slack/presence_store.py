"""Local JSON store for #presence day-scoped statuses."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.channels.slack.presence_parse import LOCATIONS, STATUSES, today_in_tz
from tempa.settings import get_settings

_lock = threading.Lock()


def _data_dir() -> Path:
    path = get_settings().sessions_dir / "presence"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _status_path() -> Path:
    return _data_dir() / "status.json"


def _sync_path() -> Path:
    return _data_dir() / "sync_state.json"


def _members_path() -> Path:
    return _data_dir() / "members.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_sync_state() -> dict[str, Any]:
    path = _sync_path()
    if not path.exists():
        return {"latest_ts": "", "seen_message_ts": [], "last_sync_at": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"latest_ts": "", "seen_message_ts": [], "last_sync_at": ""}
    return {
        "latest_ts": str(data.get("latest_ts") or ""),
        "seen_message_ts": list(data.get("seen_message_ts") or []),
        "last_sync_at": str(data.get("last_sync_at") or ""),
    }


def save_sync_state(state: dict[str, Any]) -> None:
    path = _sync_path()
    seen = list(state.get("seen_message_ts") or [])
    # ponytail: cap seen set; oldest drop — ceiling ~5k msgs before rotate
    if len(seen) > 5000:
        seen = seen[-5000:]
    payload = {
        "latest_ts": str(state.get("latest_ts") or ""),
        "seen_message_ts": seen,
        "last_sync_at": str(state.get("last_sync_at") or _now_iso()),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_statuses() -> dict[str, dict[str, Any]]:
    path = _status_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_statuses(rows: dict[str, dict[str, Any]]) -> None:
    _status_path().write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def has_seen_message(message_ts: str, *, state: dict[str, Any] | None = None) -> bool:
    if not message_ts:
        return False
    st = state if state is not None else load_sync_state()
    return message_ts in set(st.get("seen_message_ts") or [])


def upsert_presence(
    *,
    day: str,
    user_id: str,
    display_name: str,
    classification: dict[str, Any],
    message_ts: str,
    ts_iso: str = "",
) -> None:
    if not day or not user_id:
        return
    key = f"{day}:{user_id}"
    row = {
        "date": day,
        "user_id": user_id,
        "name": display_name or user_id,
        "status": classification.get("status") or "other",
        "location": classification.get("location"),
        "location_raw": classification.get("location_raw"),
        "reason": classification.get("reason"),
        "half": classification.get("half"),
        "note": classification.get("note") or "",
        "raw_text": classification.get("raw_text") or "",
        "source": classification.get("source") or "rules",
        "ts": ts_iso or _now_iso(),
        "message_ts": message_ts,
        "updated_at": _now_iso(),
    }
    with _lock:
        rows = _load_statuses()
        existing = rows.get(key)
        # latest message wins
        if existing and str(existing.get("message_ts") or "") > message_ts:
            return
        rows[key] = row
        _write_statuses(rows)


def mark_seen(message_ts: str, *, latest_ts: str | None = None) -> None:
    if not message_ts:
        return
    with _lock:
        state = load_sync_state()
        seen = list(state.get("seen_message_ts") or [])
        if message_ts not in seen:
            seen.append(message_ts)
        if latest_ts and (not state.get("latest_ts") or latest_ts > str(state.get("latest_ts"))):
            state["latest_ts"] = latest_ts
        state["seen_message_ts"] = seen
        state["last_sync_at"] = _now_iso()
        save_sync_state(state)


def load_members() -> list[dict[str, str]]:
    path = _members_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        members = data.get("members") if isinstance(data, dict) else data
        return [m for m in (members or []) if isinstance(m, dict) and m.get("user_id")]
    except Exception:
        return []


def save_members(members: list[dict[str, str]]) -> None:
    payload = {"members": members, "updated_at": _now_iso()}
    _members_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def office_location_for_email(email: str) -> str | None:
    """Route office folk to a building by email: niete -> Niete, taleemabad/rest -> HQ."""
    return "niete" if "niete" in (email or "").lower() else None


def _implied_office_entry(member: dict[str, str], day: str) -> dict[str, Any]:
    return {
        "date": day,
        "user_id": member["user_id"],
        "name": member.get("name") or member["user_id"],
        "image": member.get("image") or "",
        "status": "office",
        "location": office_location_for_email(member.get("email") or ""),
        "location_raw": None,
        "reason": None,
        "half": None,
        "note": "No update — assumed in office",
        "raw_text": "",
        "source": "implied",
        "ts": "",
        "message_ts": "",
    }


def list_for_date(day: str | None = None) -> list[dict[str, Any]]:
    target = day or today_in_tz().isoformat()
    with _lock:
        rows = _load_statuses()
    out = [r for r in rows.values() if str(r.get("date")) == target]
    out.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    return out


def build_payload(day: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    target = day or today_in_tz().isoformat()
    entries = list_for_date(target)
    groups: dict[str, list[dict[str, Any]]] = {s: [] for s in STATUSES}
    counts: dict[str, int] = {s: 0 for s in STATUSES}
    by_location: dict[str, list[dict[str, Any]]] = {loc: [] for loc in LOCATIONS}

    # Channel members with no post for the day count as present in office.
    members = load_members()
    images = {m["user_id"]: m.get("image") or "" for m in members}
    emails = {m["user_id"]: m.get("email") or "" for m in members}
    posted_ids = {str(e.get("user_id")) for e in entries}
    for entry in entries:
        uid = str(entry.get("user_id"))
        entry["image"] = images.get(uid, "")
        # Office posts without an explicit site fall back to the email-derived office
        if entry.get("status") == "office" and not entry.get("location"):
            entry["location"] = office_location_for_email(emails.get(uid, ""))
    for member in members:
        if member["user_id"] not in posted_ids:
            entries.append(_implied_office_entry(member, target))

    for entry in entries:
        status = str(entry.get("status") or "other")
        if status not in groups:
            status = "other"
        groups[status].append(entry)
        counts[status] += 1
        loc = entry.get("location")
        if loc in by_location:
            by_location[str(loc)].append(entry)

    state = load_sync_state()
    return {
        "date": target,
        "channel": {
            "id": settings.slack_presence_channel_id,
            "name": settings.slack_presence_channel_name,
        },
        "updated_at": state.get("last_sync_at") or "",
        "llm_model": settings.slack_presence_llm_model,
        "counts": counts,
        "groups": groups,
        "by_location": by_location,
    }
