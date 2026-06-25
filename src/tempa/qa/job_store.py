"""QA scan job queue."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from tempa.qa.config import qa_data_dir

_lock = threading.Lock()
JobStatus = Literal["queued", "running", "completed", "failed"]


def _queue_path() -> Path:
    p = qa_data_dir() / "job_queue.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _status_path() -> Path:
    p = qa_data_dir() / "job_status.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def enqueue_scan(
    repo: str,
    *,
    branch: str | None = None,
    job_type: str = "branch_scan",
    pr_number: int | None = None,
    installation_id: int | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    job_id = str(uuid.uuid4())
    row: dict[str, Any] = {
        "id": job_id,
        "repo": repo,
        "branch": branch,
        "job_type": job_type,
        "pr_number": pr_number,
        "installation_id": installation_id,
        "status": "queued",
        "enqueued_at": _now_iso(),
        **(extra or {}),
    }
    with _lock:
        statuses = _read_statuses()
        statuses[job_id] = dict(row)
        _write_statuses(statuses)
        with _queue_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return job_id


def claim_next_job() -> dict[str, Any] | None:
    with _lock:
        if not _queue_path().exists():
            return None
        lines = [ln for ln in _queue_path().read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not lines:
            return None
        job = json.loads(lines[0])
        remaining = lines[1:]
        _queue_path().write_text("\n".join(remaining) + ("\n" if remaining else ""), encoding="utf-8")
        statuses = _read_statuses()
        job_id = str(job.get("id") or "")
        if job_id:
            statuses[job_id] = {**statuses.get(job_id, job), "status": "running", "started_at": _now_iso()}
            _write_statuses(statuses)
        return job


def update_job_status(job_id: str, *, status: JobStatus, error: str | None = None, result: dict | None = None) -> None:
    with _lock:
        statuses = _read_statuses()
        row = statuses.get(job_id, {"id": job_id})
        row["status"] = status
        row["updated_at"] = _now_iso()
        if error:
            row["error"] = error
        if result is not None:
            row["result"] = result
        if status == "completed":
            row["completed_at"] = _now_iso()
        statuses[job_id] = row
        _write_statuses(statuses)


def list_jobs(*, limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        items = list(_read_statuses().values())
    items.sort(key=lambda r: r.get("enqueued_at", ""), reverse=True)
    return items[:limit]


def queue_depth() -> int:
    with _lock:
        if not _queue_path().exists():
            return 0
        return len([ln for ln in _queue_path().read_text(encoding="utf-8").splitlines() if ln.strip()])
