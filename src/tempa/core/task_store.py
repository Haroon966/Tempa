from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from tempa.settings import get_settings

SubtaskStatus = Literal["pending", "in_progress", "completed", "failed"]
TaskStatus = Literal["pending", "in_progress", "completed", "failed", "stale"]

_lock = threading.Lock()


def _status_path():
    return get_settings().sessions_dir / "tasks" / "task_status.json"


def _ensure_dir() -> None:
    _status_path().parent.mkdir(parents=True, exist_ok=True)


def _read_unlocked() -> dict[str, dict[str, Any]]:
    path = _status_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_unlocked(tasks: dict[str, dict[str, Any]]) -> None:
    _ensure_dir()
    _status_path().write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_task(user_message: str, subtasks: list[dict[str, Any]]) -> str:
    task_id = str(uuid.uuid4())
    now = _now_iso()
    record = {
        "id": task_id,
        "user_message": user_message[:500],
        "status": "in_progress",
        "created_at": now,
        "updated_at": now,
        "subtasks": [
            {
                "agent": t.get("agent", ""),
                "task": t.get("task", "")[:300],
                "status": "pending",
            }
            for t in subtasks
        ],
    }
    with _lock:
        tasks = _read_unlocked()
        tasks[task_id] = record
        _write_unlocked(tasks)
    return task_id


def update_subtask(task_id: str, agent: str, status: SubtaskStatus) -> None:
    with _lock:
        tasks = _read_unlocked()
        task = tasks.get(task_id)
        if not task:
            return
        for sub in task.get("subtasks", []):
            if sub.get("agent") == agent and sub.get("status") != "completed":
                sub["status"] = status
                break
        task["updated_at"] = _now_iso()
        tasks[task_id] = task
        _write_unlocked(tasks)


def complete_task(task_id: str, *, status: TaskStatus = "completed") -> None:
    with _lock:
        tasks = _read_unlocked()
        task = tasks.get(task_id)
        if not task:
            return
        task["status"] = status
        task["updated_at"] = _now_iso()
        tasks[task_id] = task
        _write_unlocked(tasks)


def list_active_tasks() -> list[dict[str, Any]]:
    with _lock:
        tasks = _read_unlocked()
    active = [t for t in tasks.values() if t.get("status") in ("pending", "in_progress")]
    active.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return active


def list_recent_tasks(limit: int = 20) -> list[dict[str, Any]]:
    with _lock:
        tasks = _read_unlocked()
    items = list(tasks.values())
    items.sort(key=lambda t: t.get("updated_at", ""), reverse=True)
    return items[:limit]


def get_task(task_id: str) -> dict[str, Any] | None:
    with _lock:
        task = _read_unlocked().get(task_id)
        return dict(task) if task else None


def sweep_stale_tasks(max_age_hours: int = 24) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    count = 0
    with _lock:
        tasks = _read_unlocked()
        for task in tasks.values():
            if task.get("status") not in ("pending", "in_progress"):
                continue
            updated = task.get("updated_at", task.get("created_at", ""))
            try:
                ts = datetime.fromisoformat(updated)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    task["status"] = "stale"
                    count += 1
            except Exception:
                pass
        _write_unlocked(tasks)
    return count


def format_active_tasks_summary() -> str:
    active = list_active_tasks()
    if not active:
        return ""
    lines = []
    for task in active[:5]:
        subs = ", ".join(
            f"{s.get('agent')}:{s.get('status')}" for s in task.get("subtasks", [])[:4]
        )
        lines.append(f"- {task.get('user_message', '')[:80]} [{subs}]")
    return "Active tasks:\n" + "\n".join(lines)
