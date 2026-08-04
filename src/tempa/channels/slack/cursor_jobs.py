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
    starter = str(fields.get("user_id") or "").strip()
    seeded = fields.get("participant_ids")
    if isinstance(seeded, list):
        participant_ids = [str(u).strip() for u in seeded if str(u).strip()]
    else:
        participant_ids = []
    if starter and starter not in participant_ids:
        participant_ids = [starter, *[u for u in participant_ids if u != starter]]
    row: dict[str, Any] = {
        "id": job_id,
        "status": "queued",
        "enqueued_at": _now_iso(),
        "updated_at": _now_iso(),
        "ci_fix_count": 0,
        "phase": "queued",
        **fields,
        "participant_ids": participant_ids,
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
        statuses = _read_statuses()
        keep: list[str] = []
        for raw in lines:
            if len(claimed) >= limit:
                keep.append(raw)
                continue
            try:
                job = json.loads(raw)
            except json.JSONDecodeError:
                continue
            job_id = str(job.get("id") or "")
            current = statuses.get(job_id) or job
            # Stale queue rows (completed/failed/interrupted) must not be re-claimed.
            if str(current.get("status") or "") != "queued":
                continue
            job = dict(current)
            job["status"] = "running"
            job["started_at"] = _now_iso()
            job["updated_at"] = _now_iso()
            job["phase"] = "running"
            if job_id:
                statuses[job_id] = job
            claimed.append(job)
        path.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
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


def find_jobs_for_thread(
    *,
    channel_id: str,
    thread_ts: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Jobs belonging to a Slack thread (newest first)."""
    ch = str(channel_id or "").strip()
    ts = str(thread_ts or "").strip()
    if not ch or not ts:
        return []
    rows = [
        r
        for r in list_jobs(limit=max(limit * 4, 80))
        if str(r.get("channel_id") or "") == ch and str(r.get("thread_ts") or "") == ts
    ]
    return rows[: max(1, limit)]


def thread_has_cursor_job(*, channel_id: str, thread_ts: str) -> bool:
    return bool(find_jobs_for_thread(channel_id=channel_id, thread_ts=thread_ts, limit=1))


def _merge_participant_ids(existing: Any, *extra: str) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in list(existing or []) + list(extra):
        uid = str(raw or "").strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        ordered.append(uid)
    return ordered


def add_thread_participants(
    *,
    channel_id: str,
    thread_ts: str,
    user_ids: list[str] | tuple[str, ...] | str,
) -> int:
    """Persist human participant ids on every Cursor job for this Slack thread.

    Returns how many jobs were updated. Idempotent.
    """
    ch = str(channel_id or "").strip()
    ts = str(thread_ts or "").strip()
    if isinstance(user_ids, str):
        incoming = [user_ids]
    else:
        incoming = list(user_ids)
    incoming = [str(u).strip() for u in incoming if str(u).strip()]
    if not ch or not ts or not incoming:
        return 0
    updated = 0
    with _lock:
        statuses = _read_statuses()
        for job_id, row in list(statuses.items()):
            if str(row.get("channel_id") or "") != ch or str(row.get("thread_ts") or "") != ts:
                continue
            merged = _merge_participant_ids(row.get("participant_ids"), *incoming)
            starter = str(row.get("user_id") or "").strip()
            if starter and starter in merged:
                merged = [starter, *[u for u in merged if u != starter]]
            if merged == list(row.get("participant_ids") or []):
                continue
            row = {**row, "participant_ids": merged, "updated_at": _now_iso()}
            statuses[job_id] = row
            updated += 1
        if updated:
            _write_statuses(statuses)
    return updated


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
