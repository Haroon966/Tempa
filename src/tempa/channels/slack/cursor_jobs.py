"""Durable Cursor Slack-thread job store (parallel Tempa agent jobs)."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from tempa.settings import get_settings

_lock = threading.Lock()

JobStatus = Literal[
    "queued",
    "running",
    "waiting_ci",
    "fixing_ci",
    "running_tests",
    "completed",
    "failed",
    "interrupted",
    "needs_help",
]

ACTIVE_STATUSES = frozenset({"queued", "running", "waiting_ci", "fixing_ci", "running_tests"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jobs_dir() -> Path:
    p = get_settings().tempa_data_dir / "cursor_jobs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _status_path() -> Path:
    return _jobs_dir() / "status.json"


def _queue_path() -> Path:
    return _jobs_dir() / "queue.jsonl"


def _read_statuses() -> dict[str, dict[str, Any]]:
    path = _status_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_statuses(statuses: dict[str, dict[str, Any]]) -> None:
    _status_path().write_text(json.dumps(statuses, ensure_ascii=False, indent=2), encoding="utf-8")


def pr_key(*, channel_id: str, thread_ts: str, user_id: str, repo: str = "") -> str:
    return f"{repo}|{channel_id}|{thread_ts}|{user_id}"


def enqueue_cursor_job(fields: dict[str, Any]) -> str:
    job_id = str(uuid.uuid4())
    row: dict[str, Any] = {
        "id": job_id,
        "status": "queued",
        "enqueued_at": _now_iso(),
        "updated_at": _now_iso(),
        "ci_fix_count": 0,
        "phase": "queued",
        **fields,
    }
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with _lock:
        statuses = _read_statuses()
        statuses[job_id] = dict(row)
        _write_statuses(statuses)
        with _queue_path().open("a", encoding="utf-8") as f:
            f.write(line)
    return job_id


def count_active_jobs() -> int:
    with _lock:
        statuses = _read_statuses()
        return sum(1 for row in statuses.values() if row.get("status") in ACTIVE_STATUSES)


def claim_next_jobs(limit: int) -> list[dict[str, Any]]:
    """Claim up to `limit` queued jobs (parallel pool)."""
    claimed: list[dict[str, Any]] = []
    if limit <= 0:
        return claimed
    with _lock:
        path = _queue_path()
        if not path.exists():
            return claimed
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not lines:
            return claimed
        take = lines[:limit]
        remaining = lines[limit:]
        path.write_text("\n".join(remaining) + ("\n" if remaining else ""), encoding="utf-8")
        statuses = _read_statuses()
        for raw in take:
            job = json.loads(raw)
            job_id = str(job.get("id") or "")
            job["status"] = "running"
            job["started_at"] = _now_iso()
            job["updated_at"] = _now_iso()
            job["phase"] = "running"
            if job_id:
                statuses[job_id] = {**statuses.get(job_id, {}), **job}
            claimed.append(job)
        _write_statuses(statuses)
    return claimed


def update_job(job_id: str, **fields: Any) -> dict[str, Any]:
    with _lock:
        statuses = _read_statuses()
        row = dict(statuses.get(job_id) or {"id": job_id})
        row.update(fields)
        row["updated_at"] = _now_iso()
        if fields.get("status") == "completed":
            row["completed_at"] = _now_iso()
        statuses[job_id] = row
        _write_statuses(statuses)
        return row


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        return _read_statuses().get(job_id)


def list_jobs(*, limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        rows = list(_read_statuses().values())
    rows.sort(key=lambda r: str(r.get("updated_at") or r.get("enqueued_at") or ""), reverse=True)
    return rows[: max(1, limit)]


def find_pr_binding(*, channel_id: str, thread_ts: str, user_id: str, repo: str = "") -> dict[str, Any] | None:
    """Latest job for this PR key that already has a pr_url/branch."""
    key = pr_key(channel_id=channel_id, thread_ts=thread_ts, user_id=user_id, repo=repo)
    with _lock:
        rows = list(_read_statuses().values())
    rows = [r for r in rows if r.get("pr_key") == key and (r.get("pr_url") or r.get("branch"))]
    rows.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    return rows[0] if rows else None


def interrupt_stale_active_jobs() -> list[dict[str, Any]]:
    """On boot: mark in-flight jobs interrupted and return them for Slack notify."""
    out: list[dict[str, Any]] = []
    with _lock:
        statuses = _read_statuses()
        for job_id, row in list(statuses.items()):
            if row.get("status") in {"running", "waiting_ci", "fixing_ci", "running_tests"}:
                row = {
                    **row,
                    "status": "interrupted",
                    "phase": "interrupted",
                    "error": "Tempa restarted while this job was in progress",
                    "updated_at": _now_iso(),
                }
                statuses[job_id] = row
                out.append(row)
        _write_statuses(statuses)
        # Drop queue lines for jobs we interrupted (they were already claimed).
    return out
