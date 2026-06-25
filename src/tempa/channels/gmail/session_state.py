from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_last_action: dict[str, Any] | None = None
_bootstrapped = False


def _path() -> Path:
    path = get_settings().sessions_dir / "gmail" / "last_action.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _bootstrap() -> None:
    global _last_action, _bootstrapped
    if _bootstrapped:
        return
    _bootstrapped = True
    p = _path()
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _last_action = data
    except Exception as exc:
        logger.warning("Failed to load gmail action state: %s", exc)


def record_gmail_action(action: dict[str, Any]) -> None:
    global _last_action
    _bootstrap()
    _last_action = dict(action)
    try:
        _path().write_text(json.dumps(_last_action, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to persist gmail action: %s", exc)


def explain_last_action() -> str | None:
    _bootstrap()
    if not _last_action:
        return None
    status = _last_action.get("status")
    reason = str(_last_action.get("reason") or "").strip()
    to = _last_action.get("to", "")
    if status == "sent":
        return f"The last email to {to or 'the recipient'} was sent successfully."
    if status == "pending":
        return f"An email to {to or 'the recipient'} is waiting for your approval in Tempa."
    if status == "blocked":
        detail = reason or "blocked by the outbound safety screen (no detail returned by the model)"
        return f"The email to {to or 'the recipient'} was blocked: {detail}"
    if status == "error":
        detail = reason or "unknown error"
        return f"The email to {to or 'the recipient'} failed: {detail}"
    if _last_action.get("error"):
        return f"Email could not be prepared: {_last_action['error']}"
    return None
