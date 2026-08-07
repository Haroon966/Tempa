"""Today's calendar meetings for the dashboard day-view."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from tempa.core.timezone import local_tz, now_local, tz_name
from tempa.meet.archive import list_meetings
from tempa.meet.quality import ACTIVE_JOB_STATUSES
from tempa.meet.service import get_meeting_jobs


def _is_all_day(raw: dict[str, Any]) -> bool:
    start = raw.get("start")
    return isinstance(start, dict) and "date" in start and "dateTime" not in start


def _archive_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row.get("title"),
        "meet_link": row.get("meet_link"),
        "started_at": row.get("started_at"),
        "ended_at": row.get("ended_at"),
        "calendar_event_id": row.get("calendar_event_id"),
        "calendar_event_start": row.get("calendar_event_start"),
        "minutes_status": row.get("minutes_status"),
        "artifacts": row.get("artifacts"),
    }


def _job_match(
    jobs: dict[str, dict[str, Any]],
    *,
    event_id: str,
    meet_url: str | None,
) -> tuple[str | None, str | None]:
    """Return (meeting_id, status) for the best matching job."""
    best: tuple[str | None, str | None] = (None, None)
    for mid, row in jobs.items():
        url = str(row.get("meet_url") or "")
        cal_id = str(row.get("calendar_event_id") or "")
        if cal_id == event_id or (meet_url and url == meet_url):
            status = str(row.get("status") or "") or None
            if status in ACTIVE_JOB_STATUSES:
                return mid, status
            if best[0] is None:
                best = (mid, status)
    return best


def _overlaps_day(start: datetime, end: datetime, day_start: datetime, day_end: datetime) -> bool:
    return start < day_end and end > day_start


async def get_todays_meetings() -> dict[str, Any]:
    """Calendar events overlapping local today, joined to archive + job status."""
    from tempa.channels.calendar.oauth import load_calendar_client

    zone = local_tz()
    now = now_local()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    time_min = day_start.astimezone(timezone.utc)
    time_max = day_end.astimezone(timezone.utc)

    calendar_events: list[Any] = []
    client = load_calendar_client()
    if client:
        calendar_events = client.list_upcoming_events(
            calendar_id="primary",
            time_min=time_min,
            time_max=time_max,
            max_results=100,
        )

    archives = await list_meetings(limit=200, include_artifacts=True)
    by_event_id: dict[str, dict[str, Any]] = {}
    by_meet_url: dict[str, dict[str, Any]] = {}
    for row in archives:
        eid = row.get("calendar_event_id")
        if isinstance(eid, str) and eid:
            by_event_id[eid] = row
        link = row.get("meet_link")
        if isinstance(link, str) and link:
            by_meet_url[link] = row

    jobs = get_meeting_jobs()
    seen_archive_ids: set[str] = set()
    events_out: list[dict[str, Any]] = []

    for ev in calendar_events:
        if not _overlaps_day(ev.start, ev.end, day_start, day_end):
            continue
        meet_url = ev.meet_url
        archive = by_event_id.get(ev.id) or (by_meet_url.get(meet_url) if meet_url else None)
        job_mid, status = _job_match(jobs, event_id=ev.id, meet_url=meet_url)
        meeting_id = (archive or {}).get("id") or job_mid
        if archive:
            seen_archive_ids.add(str(archive["id"]))
        events_out.append(
            {
                "id": ev.id,
                "summary": ev.summary,
                "start": ev.start.isoformat(),
                "end": ev.end.isoformat(),
                "meet_url": meet_url,
                "has_meet": bool(meet_url),
                "all_day": _is_all_day(ev.raw),
                "meeting_id": meeting_id or None,
                "status": status,
                "archive": _archive_payload(archive) if archive else None,
            }
        )

    # Orphan recordings from today (no matching calendar row).
    for row in archives:
        mid = str(row.get("id") or "")
        if not mid or mid in seen_archive_ids:
            continue
        started_raw = row.get("started_at") or row.get("calendar_event_start")
        if not isinstance(started_raw, str) or not started_raw:
            continue
        try:
            started = datetime.fromisoformat(started_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        local_started = started.astimezone(zone)
        if local_started < day_start or local_started >= day_end:
            continue
        ended_raw = row.get("ended_at")
        ended = local_started + timedelta(minutes=30)
        if isinstance(ended_raw, str) and ended_raw:
            try:
                ended_dt = datetime.fromisoformat(ended_raw.replace("Z", "+00:00"))
                if ended_dt.tzinfo is None:
                    ended_dt = ended_dt.replace(tzinfo=timezone.utc)
                ended = ended_dt.astimezone(zone)
            except ValueError:
                pass
        meet_url = row.get("meet_link") if isinstance(row.get("meet_link"), str) else None
        job_mid, status = _job_match(jobs, event_id=str(row.get("calendar_event_id") or ""), meet_url=meet_url)
        events_out.append(
            {
                "id": f"archive:{mid}",
                "summary": row.get("title") or "Untitled meeting",
                "start": local_started.isoformat(),
                "end": ended.isoformat(),
                "meet_url": meet_url,
                "has_meet": bool(meet_url),
                "all_day": False,
                "meeting_id": mid,
                "status": status,
                "archive": _archive_payload(row),
            }
        )

    events_out.sort(key=lambda e: e["start"])
    return {
        "date": day_start.date().isoformat(),
        "timezone": tz_name(),
        "events": events_out,
    }
