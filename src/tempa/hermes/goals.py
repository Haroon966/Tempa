"""Persistent goals + lightweight kanban for multi-day Hermes/Tempa ops.

Code changes still go through Cursor jobs — goals here track standing non-coding work.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

GoalStatus = Literal["open", "paused", "done"]
KanbanColumn = Literal["backlog", "doing", "done"]


def _hermes_dir() -> Path:
    from tempa.settings import get_settings

    path = get_settings().tempa_data_dir / "hermes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _goals_path() -> Path:
    return _hermes_dir() / "goals.json"


def _kanban_path() -> Path:
    return _hermes_dir() / "kanban.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("Failed reading %s", path, exc_info=True)
        return default


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def list_goals(*, status: str | None = None) -> list[dict[str, Any]]:
    raw = _read_json(_goals_path(), {"goals": []})
    goals = list(raw.get("goals") or []) if isinstance(raw, dict) else []
    if status:
        goals = [g for g in goals if g.get("status") == status]
    return goals


def create_goal(title: str, *, prompt: str = "", notes: str = "") -> dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise ValueError("title required")
    goal = {
        "id": str(uuid.uuid4()),
        "title": title,
        "prompt": (prompt or title).strip(),
        "notes": notes,
        "status": "open",
        "created_at": _now(),
        "updated_at": _now(),
        "last_tick_at": None,
    }
    raw = _read_json(_goals_path(), {"goals": []})
    goals = list(raw.get("goals") or []) if isinstance(raw, dict) else []
    goals.append(goal)
    _write_json(_goals_path(), {"goals": goals, "updated_at": _now()})
    add_kanban_card(goal["title"], column="doing", goal_id=goal["id"])
    return goal


def update_goal(goal_id: str, **fields: Any) -> dict[str, Any] | None:
    raw = _read_json(_goals_path(), {"goals": []})
    goals = list(raw.get("goals") or []) if isinstance(raw, dict) else []
    for goal in goals:
        if goal.get("id") != goal_id:
            continue
        for key in ("title", "prompt", "notes", "status"):
            if key in fields and fields[key] is not None:
                goal[key] = fields[key]
        goal["updated_at"] = _now()
        if fields.get("tick"):
            goal["last_tick_at"] = _now()
        _write_json(_goals_path(), {"goals": goals, "updated_at": _now()})
        if goal.get("status") == "done":
            move_kanban_by_goal(goal_id, "done")
        return dict(goal)
    return None


def open_goals_prompt_block() -> str:
    opens = list_goals(status="open")
    if not opens:
        return ""
    lines = ["## Standing goals (keep working across turns; code still via Cursor)"]
    for g in opens[:8]:
        lines.append(f"- [{g.get('id')}] {g.get('title')}: {str(g.get('prompt') or '')[:200]}")
    return "\n".join(lines)


def list_kanban() -> dict[str, list[dict[str, Any]]]:
    raw = _read_json(
        _kanban_path(),
        {"backlog": [], "doing": [], "done": []},
    )
    if not isinstance(raw, dict):
        return {"backlog": [], "doing": [], "done": []}
    return {
        "backlog": list(raw.get("backlog") or []),
        "doing": list(raw.get("doing") or []),
        "done": list(raw.get("done") or []),
    }


def add_kanban_card(
    title: str,
    *,
    column: KanbanColumn = "backlog",
    goal_id: str | None = None,
) -> dict[str, Any]:
    board = list_kanban()
    card = {
        "id": str(uuid.uuid4()),
        "title": title.strip(),
        "goal_id": goal_id,
        "created_at": _now(),
    }
    board.setdefault(column, []).append(card)
    _write_json(_kanban_path(), {**board, "updated_at": _now()})
    return card


def move_kanban_card(card_id: str, column: KanbanColumn) -> dict[str, Any] | None:
    board = list_kanban()
    found: dict[str, Any] | None = None
    for col in ("backlog", "doing", "done"):
        cards = board.get(col) or []
        keep: list[dict[str, Any]] = []
        for card in cards:
            if card.get("id") == card_id:
                found = dict(card)
            else:
                keep.append(card)
        board[col] = keep
    if not found:
        return None
    board.setdefault(column, []).append(found)
    _write_json(_kanban_path(), {**board, "updated_at": _now()})
    return found


def move_kanban_by_goal(goal_id: str, column: KanbanColumn) -> None:
    board = list_kanban()
    for col in ("backlog", "doing", "done"):
        for card in board.get(col) or []:
            if card.get("goal_id") == goal_id:
                move_kanban_card(str(card["id"]), column)
                return
