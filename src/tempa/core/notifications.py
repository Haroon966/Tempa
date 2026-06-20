from __future__ import annotations

import logging
import platform
import subprocess
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

from tempa.core.events import event_bus

logger = logging.getLogger(__name__)

_history: deque[dict[str, Any]] = deque(maxlen=100)
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _desktop_notify(title: str, body: str) -> None:
    system = platform.system()
    try:
        if system == "Linux":
            subprocess.run(
                ["notify-send", title, body[:240]],
                check=False,
                capture_output=True,
                timeout=5,
            )
        elif system == "Darwin":
            script = f'display notification "{body[:200]}" with title "{title[:60]}"'
            subprocess.run(["osascript", "-e", script], check=False, capture_output=True, timeout=5)
    except Exception as exc:
        logger.debug("Desktop notification failed: %s", exc)


async def notify(
    event_type: str,
    *,
    title: str,
    body: str = "",
    pending_action_id: str | None = None,
    task_id: str | None = None,
    extra: dict[str, Any] | None = None,
    desktop: bool = True,
) -> dict[str, Any]:
    record = {
        "type": event_type,
        "title": title,
        "body": body,
        "timestamp": _now_iso(),
        "pending_action_id": pending_action_id,
        "task_id": task_id,
        **(extra or {}),
    }
    with _lock:
        _history.append(record)

    if desktop:
        _desktop_notify(title, body)

    detail = body[:120] if body else title[:120]
    await event_bus.publish(
        {
            "agent": "notification",
            "action": event_type,
            "detail": detail,
            "timestamp": record["timestamp"],
            "notification_type": event_type,
            "pending_action_id": pending_action_id,
            "task_id": task_id,
            "title": title,
            "body": body,
        }
    )
    return record


def recent_notifications(limit: int = 30) -> list[dict[str, Any]]:
    with _lock:
        return list(_history)[-limit:]
