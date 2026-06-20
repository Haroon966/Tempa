from __future__ import annotations

import time
from typing import Any

from tempa.channels.gmail.session_state import explain_last_action as explain_gmail_action
from tempa.channels.gmail.session_state import record_gmail_action

_last_actions: dict[str, dict[str, Any]] = {}
_last_action_channel: str | None = None
_last_action_at: float = 0.0


def record_action(channel: str, action: dict[str, Any]) -> None:
    global _last_action_channel, _last_action_at
    stamped = {**action, "_ts": time.time()}
    _last_actions[channel] = stamped
    _last_action_channel = channel
    _last_action_at = stamped["_ts"]
    if channel == "gmail":
        record_gmail_action(action)


def explain_last_action(channel: str | None = None) -> str | None:
    from tempa.core.pending_actions import list_pending_actions
    from tempa.core.task_store import list_active_tasks

    pending = list_pending_actions(status="pending")
    if pending:
        titles = "; ".join(a.get("title", a.get("type", "")) for a in pending[:3])
        return f"Pending your approval: {titles}. Open Tempa to review."

    active = list_active_tasks()
    if active:
        msg = active[0].get("user_message", "")[:80]
        return f"Task in progress: {msg}"

    if channel:
        if channel == "gmail":
            return explain_gmail_action()
        action = _last_actions.get(channel)
        if not action:
            return None
        return _format_action(channel, action)

    if _last_action_channel and _last_action_channel in _last_actions:
        return _format_action(_last_action_channel, _last_actions[_last_action_channel])

    for ch in ("gmail", "meet", "calendar", "whatsapp"):
        if ch == "gmail":
            text = explain_gmail_action()
            if text:
                return text
            continue
        action = _last_actions.get(ch)
        if action:
            return _format_action(ch, action)
    return None


def _format_action(channel: str, action: dict[str, Any]) -> str:
    status = action.get("status")
    reason = str(action.get("reason") or action.get("error") or "").strip()
    if channel == "meet":
        mid = action.get("meeting_id", "")
        url = action.get("meet_url", "")
        if status == "queued":
            return f"Meet join queued (job {mid or 'pending'}) for {url or 'the meeting'}."
        if status == "running":
            return f"Meet bot is joining/recording {url or mid}."
        if status == "completed":
            return f"Meet job {mid} completed successfully."
        if status == "failed":
            return f"Meet join failed: {reason or 'unknown error'}"
    if channel == "calendar":
        summary = action.get("summary", "the meeting")
        attendees = action.get("attendees") or []
        if status == "created":
            line = f"Created calendar event '{summary}'"
            if action.get("when"):
                line += f" at {action['when']}"
            if attendees:
                line += f" and sent invite to {', '.join(attendees)}"
            elif not attendees:
                line += " (no guests were added — only on your calendar)"
            return line + "."
        if status == "invited":
            guests = ", ".join(attendees) if attendees else "the guest"
            return f"Sent calendar invite for '{summary}' to {guests}."
        if status == "deleted":
            return f"Deleted calendar event '{summary}'."
        if status == "error":
            return f"Calendar action failed: {reason or 'unknown error'}"
    if status == "blocked":
        return f"{channel.title()} action blocked: {reason or 'safety screen'}"
    if status == "error":
        return f"{channel.title()} action failed: {reason or 'unknown error'}"
    if status == "sent":
        return f"{channel.title()} action succeeded."
    return f"Last {channel} action: {status or 'unknown'}"
