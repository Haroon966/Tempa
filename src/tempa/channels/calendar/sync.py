from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any

from tempa.channels.calendar.client import CalendarEvent
from tempa.channels.calendar.ingest import extract_participants, ingest_calendar_event
from tempa.channels.calendar.oauth import load_calendar_client
from tempa.rag.purge import purge_calendar_event
from tempa.settings import get_settings

logger = logging.getLogger(__name__)


def _snapshot_path() -> Path:
    path = get_settings().sessions_dir / "calendar" / "snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_calendar_snapshot() -> dict[str, Any]:
    path = _snapshot_path()
    if not path.exists():
        return {"events": [], "last_sync_at": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"events": [], "last_sync_at": ""}


def save_calendar_snapshot(data: dict[str, Any]) -> None:
    path = _snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def event_to_snapshot(ev: CalendarEvent) -> dict[str, Any]:
    raw = ev.raw if isinstance(ev.raw, dict) else {}
    description = raw.get("description")
    if isinstance(description, str):
        description = description.strip()[:2000]
    else:
        description = ""
    status = str(raw.get("status") or "confirmed")
    location = str(raw.get("location") or "")
    updated = str(raw.get("updated") or "")
    return {
        "id": ev.id,
        "summary": ev.summary,
        "start": ev.start.isoformat(),
        "end": ev.end.isoformat(),
        "status": status,
        "description": description,
        "attendees": extract_participants(raw),
        "meet_url": ev.meet_url,
        "location": location,
        "updated": updated,
    }


def remove_event_from_snapshot(event_id: str) -> None:
    data = load_calendar_snapshot()
    events = data.get("events") or []
    data["events"] = [e for e in events if isinstance(e, dict) and e.get("id") != event_id]
    save_calendar_snapshot(data)


def sync_calendar_snapshot(
    *,
    days_past: int = 14,
    days_future: int = 30,
    max_results: int = 250,
) -> dict[str, Any]:
    """Fetch calendar events, reconcile snapshot, ingest/purge RAG."""
    client = load_calendar_client()
    if client is None:
        return {"status": "skipped", "reason": "Google Calendar not connected"}

    now = dt.datetime.now(dt.timezone.utc)
    time_min = now - dt.timedelta(days=days_past)
    time_max = now + dt.timedelta(days=days_future)

    try:
        events = client.list_upcoming_events(
            calendar_id="primary",
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
            include_cancelled=True,
        )
    except Exception as exc:
        logger.exception("Calendar snapshot fetch failed")
        return {"status": "error", "reason": str(exc)}

    previous = load_calendar_snapshot()
    prev_by_id: dict[str, dict[str, Any]] = {
        str(e["id"]): e for e in (previous.get("events") or []) if isinstance(e, dict) and e.get("id")
    }

    current_rows: list[dict[str, Any]] = []
    ingested = 0
    purged = 0

    for ev in events:
        row = event_to_snapshot(ev)
        current_rows.append(row)
        event_id = str(row["id"])
        status = row.get("status", "confirmed")

        if status == "cancelled":
            removed = purge_calendar_event(event_id)
            if removed:
                purged += removed
            continue

        prev = prev_by_id.get(event_id)
        changed = (
            prev is None
            or prev.get("updated") != row.get("updated")
            or prev.get("summary") != row.get("summary")
            or prev.get("status") != row.get("status")
        )
        if changed:
            try:
                ingest_calendar_event(ev)
                ingested += 1
            except Exception:
                logger.exception("Failed to ingest calendar event %s", event_id)

    current_ids = {str(r["id"]) for r in current_rows}
    for old_id in prev_by_id:
        if old_id not in current_ids:
            removed = purge_calendar_event(old_id)
            if removed:
                purged += removed

    snapshot = {
        "last_sync_at": now.isoformat(),
        "events": [r for r in current_rows if r.get("status") != "cancelled"],
        "cancelled_events": [r for r in current_rows if r.get("status") == "cancelled"],
    }
    save_calendar_snapshot(snapshot)
    return {
        "status": "ok",
        "events": len(current_rows),
        "ingested": ingested,
        "purged": purged,
    }
