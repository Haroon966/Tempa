from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.settings import get_settings

_lock = threading.Lock()


def _queue_path() -> Path:
    return get_settings().sessions_dir / "meet" / "job_queue.jsonl"


def _status_path() -> Path:
    return get_settings().sessions_dir / "meet" / "job_status.json"


def _ensure_dir() -> None:
    _queue_path().parent.mkdir(parents=True, exist_ok=True)


def recover_stale_running_jobs(
    *,
    max_age_minutes: int = 10,
    on_startup: bool = False,
    active_meeting_ids: set[str] | frozenset[str] | None = None,
) -> int:
    """Recover meet jobs stuck in running/finalizing (e.g. after worker crash).

    On worker startup, orphaned in-flight jobs become ``interrupted`` so the
    worker can run the normal finalize path. During normal operation, only jobs
    older than *max_age_minutes* are touched, and jobs still owned by this
    worker (*active_meeting_ids*) are never touched.
    """
    _ensure_dir()
    now = datetime.now(timezone.utc)
    recovered = 0
    changed = False
    stale_statuses = ("running", "finalizing")
    owned = active_meeting_ids or frozenset()
    with _lock:
        statuses = _read_statuses_unlocked()
        queue_lines: list[str] = []
        if _queue_path().exists():
            queue_lines = [ln for ln in _queue_path().read_text(encoding="utf-8").splitlines() if ln.strip()]

        all_queued = _parse_queue_lines(queue_lines)
        queued_urls = {str(row.get("meet_url") or "") for row in all_queued if row.get("status") == "queued"}

        for job_id, row in list(statuses.items()):
            if row.get("status") not in stale_statuses:
                continue
            if job_id in owned:
                continue
            started_at = str(row.get("started_at") or row.get("enqueued_at") or "")
            if not on_startup and started_at:
                try:
                    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=timezone.utc)
                    age_min = (now - started).total_seconds() / 60.0
                    if age_min < max_age_minutes:
                        continue
                except Exception:
                    pass
            meet_url = str(row.get("meet_url") or "")
            if not meet_url:
                statuses[job_id] = {**row, "status": "failed", "error": "missing meet_url"}
                changed = True
                continue
            if meet_url in queued_urls:
                statuses[job_id] = {**row, "status": "failed", "error": "superseded by newer queued job"}
                changed = True
                continue
            if on_startup or row.get("status") == "finalizing":
                err = (
                    "finalization interrupted by worker restart"
                    if row.get("status") == "finalizing"
                    else "worker session interrupted"
                )
                statuses[job_id] = {
                    **row,
                    "status": "interrupted",
                    "error": err,
                    "leave_reason": "worker_interrupted",
                }
                changed = True
                recovered += 1
                continue
            # Mid-flight stale during normal operation: re-queue for another attempt.
            statuses[job_id] = {**row, "status": "queued"}
            requeue = {
                "id": job_id,
                "meet_url": meet_url,
                "title": row.get("title", ""),
                "notify_number": row.get("notify_number"),
                "enqueued_at": now.isoformat(),
                "status": "queued",
            }
            for field in (
                "calendar_event_id",
                "calendar_event_start",
                "calendar_event_end",
                "attendee_emails",
                "organizer_email",
                "duration_seconds",
                "av_test_youtube_url",
            ):
                if row.get(field) is not None:
                    requeue[field] = row[field]
            queue_lines.append(json.dumps(requeue, ensure_ascii=False))
            recovered += 1
            changed = True
        if changed:
            _queue_path().write_text("\n".join(queue_lines) + ("\n" if queue_lines else ""), encoding="utf-8")
            _write_statuses_unlocked(statuses)
    return recovered


def list_interrupted_job_ids() -> list[str]:
    """Job ids awaiting finalize after a worker interrupt."""
    with _lock:
        statuses = _read_statuses_unlocked()
    return [job_id for job_id, row in statuses.items() if row.get("status") == "interrupted"]


def _active_job_for_url_unlocked(meet_url: str) -> str | None:
    from tempa.meet.quality import ACTIVE_JOB_STATUSES

    if not meet_url:
        return None
    statuses = _read_statuses_unlocked()
    for job_id, row in statuses.items():
        if row.get("meet_url") == meet_url and row.get("status") in ACTIVE_JOB_STATUSES:
            return job_id
    return None


def has_active_job_for_url(meet_url: str) -> bool:
    with _lock:
        return _active_job_for_url_unlocked(meet_url) is not None


def _parse_utc_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def latest_job_for_url(meet_url: str) -> tuple[str, dict[str, Any]] | None:
    """Most recent job row for a Meet URL (by started_at / enqueued_at)."""
    if not meet_url:
        return None
    with _lock:
        statuses = _read_statuses_unlocked()
    best: tuple[str, dict[str, Any], datetime] | None = None
    for job_id, row in statuses.items():
        if row.get("meet_url") != meet_url:
            continue
        ts = _parse_utc_timestamp(str(row.get("started_at") or row.get("enqueued_at") or ""))
        if ts is None:
            ts = datetime.min.replace(tzinfo=timezone.utc)
        if best is None or ts >= best[2]:
            best = (job_id, row, ts)
    if best is None:
        return None
    return best[0], best[1]


def _jobs_for_event(
    statuses: dict[str, dict[str, Any]],
    *,
    meet_url: str,
    calendar_event_id: str | None,
) -> list[tuple[str, dict[str, Any]]]:
    event_id = (calendar_event_id or "").strip()
    rows: list[tuple[str, dict[str, Any]]] = []
    for job_id, row in statuses.items():
        if event_id:
            if str(row.get("calendar_event_id") or "").strip() != event_id:
                continue
        elif row.get("meet_url") != meet_url:
            continue
        rows.append((job_id, row))
    return rows


def _job_has_speech(row: dict[str, Any]) -> bool:
    try:
        return int(row.get("segment_count") or 0) > 0
    except (TypeError, ValueError):
        return False


def event_needs_coverage(
    meet_url: str,
    *,
    calendar_event_id: str | None = None,
    event_end: str | datetime | None = None,
    debounce_seconds: int = 45,
) -> bool:
    """True when the calendar event still needs a Meet join attempt.

    Coverage closes once any job for the event is ``completed`` (speech) or
    ``empty`` (definitive no-humans). Never joins after ``event_end``.
    """
    from tempa.meet.quality import ACTIVE_JOB_STATUSES, TERMINAL_COVERED_STATUSES

    if not meet_url:
        return False

    end_ts: datetime | None
    if event_end is None:
        end_ts = None
    elif isinstance(event_end, str):
        end_ts = _parse_utc_timestamp(event_end)
    else:
        # datetime-like (avoid isinstance(datetime) so tests can patch datetime.now)
        end_ts = event_end  # type: ignore[assignment]
        if getattr(end_ts, "tzinfo", None) is None:
            end_ts = end_ts.replace(tzinfo=timezone.utc)  # type: ignore[union-attr]
    now = datetime.now(timezone.utc)
    if end_ts is not None and now >= end_ts:
        return False

    with _lock:
        statuses = _read_statuses_unlocked()
        if _active_job_for_url_unlocked(meet_url):
            return False
        jobs = _jobs_for_event(statuses, meet_url=meet_url, calendar_event_id=calendar_event_id)

    if not jobs:
        # Fall back to URL-scoped jobs when event id was not stored on older rows.
        if calendar_event_id:
            with _lock:
                statuses = _read_statuses_unlocked()
                jobs = _jobs_for_event(statuses, meet_url=meet_url, calendar_event_id=None)
        if not jobs:
            return True

    for _job_id, row in jobs:
        status = str(row.get("status") or "")
        if status in TERMINAL_COVERED_STATUSES:
            return False
        if status == "completed" or status == "empty":
            return False
        if _job_has_speech(row):
            return False

    # Latest attempt debounce (anti-stampede only).
    latest = max(
        jobs,
        key=lambda item: _parse_utc_timestamp(str(item[1].get("started_at") or item[1].get("enqueued_at") or ""))
        or datetime.min.replace(tzinfo=timezone.utc),
    )
    latest_row = latest[1]
    latest_status = str(latest_row.get("status") or "")
    if latest_status in ACTIVE_JOB_STATUSES:
        return False

    started = _parse_utc_timestamp(str(latest_row.get("started_at") or latest_row.get("enqueued_at") or ""))
    if started is not None and (now - started).total_seconds() < debounce_seconds:
        return False

    # Mid-event failure with no speech yet: allow another join while event live.
    if latest_status == "failed" and not _job_has_speech(latest_row):
        return True

    # interrupted should be drained by finalize, not re-joined.
    if latest_status == "interrupted":
        return False

    # Unknown legacy terminal — do not spam.
    return False


def should_retry_calendar_join(
    meet_url: str,
    *,
    calendar_event_id: str | None = None,
    event_end: str | None = None,
    cooldown_seconds: int = 45,
) -> bool:
    """Compatibility wrapper: event coverage decides whether to re-join."""
    latest = latest_job_for_url(meet_url)
    row = latest[1] if latest else {}
    return event_needs_coverage(
        meet_url,
        calendar_event_id=calendar_event_id or (str(row.get("calendar_event_id") or "") or None),
        event_end=event_end or row.get("calendar_event_end"),
        debounce_seconds=cooldown_seconds,
    )


def enqueue_meet_job(
    meet_url: str,
    *,
    title: str = "",
    meeting_id: str | None = None,
    notify_number: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    _ensure_dir()
    with _lock:
        existing = _active_job_for_url_unlocked(meet_url)
        if existing:
            return existing
        mid = meeting_id or str(uuid.uuid4())
        row = {
            "id": mid,
            "meet_url": meet_url,
            "title": title,
            "notify_number": notify_number,
            "enqueued_at": datetime.now(timezone.utc).isoformat(),
            "status": "queued",
        }
        if extra:
            row.update(extra)
        with _queue_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        statuses = _read_statuses_unlocked()
        statuses[mid] = {"status": "queued", "meet_url": meet_url, "title": title, **(extra or {})}
        _write_statuses_unlocked(statuses)
        return mid


def _parse_queue_lines(lines: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _dedupe_queued_jobs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the newest queued job per meet_url."""
    newest_by_url: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("status") != "queued":
            continue
        meet_url = str(row.get("meet_url") or "")
        if not meet_url:
            continue
        existing = newest_by_url.get(meet_url)
        if existing is None or str(row.get("enqueued_at") or "") >= str(existing.get("enqueued_at") or ""):
            newest_by_url[meet_url] = row
    deduped = list(newest_by_url.values())
    deduped.sort(key=lambda r: str(r.get("enqueued_at") or ""), reverse=True)
    return deduped


def fail_running_job(meeting_id: str, *, error: str = "cancelled") -> None:
    with _lock:
        statuses = _read_statuses_unlocked()
        row = statuses.get(meeting_id)
        if not row or row.get("status") != "running":
            return
        statuses[meeting_id] = {**row, "status": "failed", "error": error}
        _write_statuses_unlocked(statuses)


def claim_next_job() -> dict[str, Any] | None:
    _ensure_dir()
    with _lock:
        if not _queue_path().exists():
            return None
        lines = _queue_path().read_text(encoding="utf-8").splitlines()
        all_rows = _parse_queue_lines(lines)
        candidates = _dedupe_queued_jobs(all_rows)
        claimed = candidates[0] if candidates else None
        if not claimed:
            return None

        claimed_id = str(claimed["id"])
        claimed_url = str(claimed.get("meet_url") or "")
        remaining_rows: list[dict[str, Any]] = []
        for row in all_rows:
            row_id = str(row.get("id") or "")
            row_url = str(row.get("meet_url") or "")
            if row_id == claimed_id:
                continue
            if row.get("status") == "queued" and row_url == claimed_url:
                continue
            remaining_rows.append(row)

        _queue_path().write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in remaining_rows)
            + ("\n" if remaining_rows else ""),
            encoding="utf-8",
        )
        statuses = _read_statuses_unlocked()
        for job_id, row in list(statuses.items()):
            if job_id != claimed_id and row.get("status") == "queued" and row.get("meet_url") == claimed_url:
                statuses[job_id] = {**row, "status": "skipped", "error": "superseded by newer job"}
        for row in all_rows:
            row_id = str(row.get("id") or "")
            row_url = str(row.get("meet_url") or "")
            if (
                row_id
                and row_id != claimed_id
                and row.get("status") == "queued"
                and row_url == claimed_url
                and row_id not in statuses
            ):
                statuses[row_id] = {
                    "status": "skipped",
                    "meet_url": row_url,
                    "title": row.get("title", ""),
                    "error": "superseded by newer job",
                }
        prior = statuses.get(claimed_id, {})
        statuses[claimed_id] = {
            **prior,
            **{k: v for k, v in claimed.items() if k not in ("status", "enqueued_at")},
            "status": "running",
            "meet_url": claimed.get("meet_url"),
            "title": claimed.get("title", prior.get("title", "")),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_statuses_unlocked(statuses)
        return claimed


def update_job_status(meeting_id: str, **fields: Any) -> None:
    with _lock:
        statuses = _read_statuses_unlocked()
        current = statuses.get(meeting_id, {})
        current.update(fields)
        statuses[meeting_id] = current
        _write_statuses_unlocked(statuses)


def get_all_job_statuses() -> dict[str, dict[str, Any]]:
    with _lock:
        return _read_statuses_unlocked()


def _read_statuses_unlocked() -> dict[str, dict[str, Any]]:
    path = _status_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_statuses_unlocked(statuses: dict[str, dict[str, Any]]) -> None:
    _ensure_dir()
    _status_path().write_text(json.dumps(statuses, indent=2), encoding="utf-8")
