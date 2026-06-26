from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _parse_ts(value: str) -> float:
    if not value:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return 0.0


def _normalize_turn(
    *,
    role: str,
    text: str,
    channel: str,
    timestamp: str = "",
) -> dict[str, Any] | None:
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    return {
        "role": role or "user",
        "text": cleaned,
        "content": cleaned,
        "channel": channel,
        "timestamp": timestamp or "",
    }


def _slack_turns(limit: int) -> list[dict[str, Any]]:
    from tempa.channels.slack.conversation import get_recent_messages

    turns: list[dict[str, Any]] = []
    for row in get_recent_messages(limit):
        turn = _normalize_turn(
            role=str(row.get("role") or "user"),
            text=str(row.get("text") or ""),
            channel="slack",
            timestamp=str(row.get("timestamp") or ""),
        )
        if turn:
            turns.append(turn)
    return turns


def _whatsapp_turns(limit: int) -> list[dict[str, Any]]:
    from tempa.channels.whatsapp.conversation import get_recent_messages

    turns: list[dict[str, Any]] = []
    for row in get_recent_messages(limit):
        turn = _normalize_turn(
            role=str(row.get("role") or "user"),
            text=str(row.get("text") or ""),
            channel="whatsapp",
            timestamp=str(row.get("timestamp") or ""),
        )
        if turn:
            turns.append(turn)
    return turns


def _dashboard_turns(context: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    from tempa.core.chat_sessions import get_session, list_sessions

    sessions: list[dict[str, Any]] = []
    session_id = context.get("session_id")
    if session_id:
        session = get_session(str(session_id))
        if session:
            sessions.append(session)
    else:
        for entry in list_sessions()[:3]:
            session = get_session(str(entry.get("id") or ""))
            if session:
                sessions.append(session)

    turns: list[dict[str, Any]] = []
    for session in sessions:
        for msg in (session.get("messages") or [])[-limit:]:
            turn = _normalize_turn(
                role=str(msg.get("role") or "user"),
                text=str(msg.get("content") or ""),
                channel="dashboard",
                timestamp=str(msg.get("created_at") or ""),
            )
            if turn:
                turns.append(turn)
    return turns


def collect_cross_channel_conversation(
    context: dict[str, Any] | None = None,
    *,
    per_channel_limit: int = 8,
    total_limit: int = 24,
) -> list[dict[str, Any]]:
    """Merge recent turns from dashboard, Slack, and WhatsApp chronologically."""
    ctx = dict(context or {})
    merged: list[dict[str, Any]] = []
    merged.extend(_dashboard_turns(ctx, per_channel_limit))
    merged.extend(_slack_turns(per_channel_limit))
    merged.extend(_whatsapp_turns(per_channel_limit))

    merged.sort(key=lambda row: _parse_ts(str(row.get("timestamp") or "")))

    if total_limit > 0:
        merged = merged[-total_limit:]
    return merged


def enrich_conversation_context(context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Attach unified cross-channel conversation history to coordinator context."""
    ctx = dict(context or {})
    turns = collect_cross_channel_conversation(ctx)
    if turns:
        ctx["recent_conversation"] = turns
        ctx["cross_channel_loaded"] = True
        ctx["recent_user_messages"] = [
            str(row.get("text") or row.get("content") or "")
            for row in turns
            if row.get("role") == "user"
        ][-8:]
    return ctx


def format_conversation_lines(turns: list[dict[str, Any]], *, limit: int = 16) -> list[str]:
    lines: list[str] = []
    for turn in turns[-limit:]:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "user")
        text = str(turn.get("text") or turn.get("content") or "")[:500]
        if not text:
            continue
        channel = str(turn.get("channel") or "unknown")
        lines.append(f"[{channel}] {role}: {text}")
    return lines
