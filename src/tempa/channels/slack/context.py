from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tempa.channels.slack.session import slack_configured
from tempa.channels.slack.snapshot import load_slack_snapshot
from tempa.channels.slack.sync import load_sync_state
from tempa.core.text import truncate


def _ts_label(ts: str) -> str:
    if not ts:
        return ""
    try:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ts


def build_slack_context_pack() -> dict[str, Any]:
    snapshot = load_slack_snapshot()
    sync_state = load_sync_state()
    configured = slack_configured()
    status = "Slack: connected" if configured else "Slack: not configured"
    last_sync = sync_state.get("last_sync_at") or snapshot.get("last_sync_at") or "never"
    return {
        "connection_status": f"{status} (last sync {last_sync})",
        "channels": list(snapshot.get("channels") or [])[:15],
        "recent_messages": list(snapshot.get("recent_messages") or [])[:15],
        "last_sync_at": last_sync,
    }


def format_slack_context_for_prompt(pack: dict[str, Any], *, compact: bool = True) -> str:
    if "not configured" in pack.get("connection_status", ""):
        return pack["connection_status"]

    parts: list[str] = [pack.get("connection_status") or ""]
    channels = pack.get("channels") or []
    if channels:
        lines = [f"- {c.get('name', c.get('id', '?'))}" for c in channels[:10]]
        parts.append("Slack channels/DMs:\n" + "\n".join(lines))

    recent = pack.get("recent_messages") or []
    if recent:
        lines = []
        limit = 120 if compact else 300
        for msg in recent[:10 if compact else 20]:
            lines.append(
                f"- {_ts_label(str(msg.get('ts', '')))} {msg.get('channel', '?')}: "
                f"{msg.get('user', '?')}: {truncate(str(msg.get('text') or ''), limit)}"
            )
        parts.append("Recent Slack messages:\n" + "\n".join(lines))
    elif not channels:
        parts.append("No Slack messages in snapshot yet.")

    return "\n\n".join(p for p in parts if p)
