from __future__ import annotations

from typing import Any

from tempa.channels.slack.snapshot import load_slack_snapshot
from tempa.core.text import truncate


def is_dm_event(event: dict[str, Any]) -> bool:
    channel_id = str(event.get("channel") or "")
    return event.get("channel_type") == "im" or channel_id.startswith("D")


def thread_root(event: dict[str, Any]) -> str:
    message_ts = str(event.get("ts") or "")
    return str(event.get("thread_ts") or message_ts)


def reply_thread_ts(event: dict[str, Any], *, event_type: str) -> str:
    """Thread ts for outbound replies — channel mentions and thread follow-ups stay in-thread."""
    if event_type == "app_mention":
        return thread_root(event)
    if event.get("thread_ts"):
        return str(event.get("thread_ts"))
    return ""


def should_handle_channel_thread(event: dict[str, Any], text: str) -> bool:
    """Route channel thread messages after Tempa has participated or a Jira draft is active."""
    if is_dm_event(event) or not event.get("thread_ts"):
        return False
    channel_id = str(event.get("channel") or "")
    thread_ts = str(event.get("thread_ts") or "")
    if not channel_id or not thread_ts:
        return False

    from tempa.channels.slack.conversation import bot_participated_in_thread
    from tempa.channels.slack.varys_bridge import enrich_slack_context

    ctx = enrich_slack_context(event, {})
    conv_key = str(ctx.get("slack_conversation_key") or thread_ts)
    if bot_participated_in_thread(channel_id, conv_key):
        return True

    try:
        from tempa.channels.jira.intent import is_ticket_confirm, wants_jira_ticket_edit
        from tempa.channels.jira.tickets import should_route_to_jira_ticket, ticket_feature_enabled

        if not ticket_feature_enabled():
            return False
        if should_route_to_jira_ticket(text, ctx):
            return True
        normalized = (text or "").strip()
        if normalized and (is_ticket_confirm(normalized) or wants_jira_ticket_edit(normalized)):
            return True
    except Exception:
        pass
    return False


def build_slack_context_pack() -> dict[str, Any]:
    """Workspace snapshot for LLM grounding when no local thread exists."""
    snapshot = load_slack_snapshot()
    channels = snapshot.get("channels") or []
    recent = snapshot.get("recent_messages") or []
    channel_names = {str(c.get("id") or ""): str(c.get("name") or "") for c in channels if isinstance(c, dict)}

    formatted_lines: list[str] = []
    for row in recent[:20]:
        if not isinstance(row, dict):
            continue
        ch = str(row.get("channel") or channel_names.get(str(row.get("channel_id") or ""), "channel"))
        user = str(row.get("user") or "user")
        text = truncate(str(row.get("text") or ""), 300)
        if text:
            formatted_lines.append(f"#{ch} — {user}: {text}")

    return {
        "last_sync_at": str(snapshot.get("last_sync_at") or ""),
        "channels": channels,
        "recent_messages": recent,
        "formatted_recent": "\n".join(formatted_lines) if formatted_lines else "No synced Slack messages.",
        "channel_count": len(channels),
    }


def format_slack_context_for_prompt(pack: dict[str, Any], *, compact: bool = False) -> str:
    body = pack.get("formatted_recent") or "No synced Slack messages."
    sync_at = pack.get("last_sync_at") or ""
    label = "Slack workspace (recent)"
    if sync_at and not compact:
        return f"{label}, last sync {sync_at[:19]}:\n{body}"
    if compact:
        lines = (pack.get("recent_messages") or [])[:3]
        short = []
        for row in lines:
            if isinstance(row, dict) and row.get("text"):
                short.append(truncate(str(row["text"]), 80))
        if short:
            return f"{label}: " + " | ".join(short)
    return f"{label}:\n{body}"
