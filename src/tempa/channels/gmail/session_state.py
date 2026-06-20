from __future__ import annotations

from typing import Any

_last_action: dict[str, Any] | None = None


def record_gmail_action(action: dict[str, Any]) -> None:
    global _last_action
    _last_action = dict(action)


def explain_last_action() -> str | None:
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
