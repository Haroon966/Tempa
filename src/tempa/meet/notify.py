from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def format_meeting_summary(
    title: str,
    minutes: dict[str, Any],
    *,
    meet_link: str = "",
    for_slack: bool = False,
    live_notes_excerpt: str = "",
) -> str:
    """Build a rich post-meeting summary for Slack (mrkdwn) or WhatsApp."""
    bold = "*" if for_slack else "*"
    summary = str(minutes.get("tldr") or minutes.get("summary") or "").strip()
    if not summary and live_notes_excerpt.strip():
        summary = live_notes_excerpt.strip()[:2000]
    if not summary:
        summary = "Meeting completed — see live notes and transcript in Tempa dashboard."
    lines = [f"{bold}{title}{bold} ended.", "", summary]

    decisions = minutes.get("decisions") or []
    if decisions:
        lines.append("")
        lines.append(f"{bold}Decisions{bold}")
        for item in decisions[:4]:
            if isinstance(item, dict):
                text = str(item.get("summary") or item.get("text") or "").strip()
            else:
                text = str(item).strip()
            if text:
                lines.append(f"• {text}")

    action_items = minutes.get("action_items") or []
    if action_items:
        lines.append("")
        lines.append(f"{bold}Action items{bold}")
        for item in action_items[:6]:
            if isinstance(item, dict):
                owner = str(item.get("owner") or "Unassigned").strip()
                task = str(item.get("task") or "").strip()
                due = str(item.get("due") or "").strip()
                line = f"• {owner}: {task}"
                if due:
                    line += f" (due {due})"
            else:
                line = f"• {item}"
            lines.append(line)

    open_qs = minutes.get("open_questions") or []
    if open_qs:
        lines.append("")
        lines.append(f"{bold}Open questions{bold}")
        for item in open_qs[:3]:
            if isinstance(item, dict):
                q = str(item.get("question") or "").strip()
            else:
                q = str(item).strip()
            if q:
                lines.append(f"• {q}")

    highlights = minutes.get("highlights") or minutes.get("key_points") or []
    if highlights:
        lines.append("")
        lines.append(f"{bold}Highlights{bold}")
        for point in highlights[:5]:
            lines.append(f"• {str(point).strip()}")

    if meet_link:
        lines.append("")
        lines.append(f"Link: {meet_link}")

    lines.append("")
    lines.append("Full transcript and minutes are in the Tempa dashboard.")
    text = "\n".join(lines)
    return text[:3900] if for_slack else text[:3500]


async def notify_meeting_completed(
    record: dict[str, Any],
    minutes: dict[str, Any],
    *,
    notify_number: str | None = None,
    live_notes_excerpt: str = "",
) -> dict[str, str]:
    """Send post-meeting summary to owner WhatsApp and Slack DM."""
    from tempa.settings import get_settings

    settings = get_settings()
    title = str(record.get("title") or "Meeting")
    meet_link = str(record.get("meet_link") or "")
    results: dict[str, str] = {}

    if notify_number and settings.meet_auto_send_summary_whatsapp:
        from tempa.channels.whatsapp.outbound import send_whatsapp_message

        msg = format_meeting_summary(
            title, minutes, meet_link=meet_link, for_slack=False, live_notes_excerpt=live_notes_excerpt
        )
        try:
            sent = await send_whatsapp_message(
                notify_number,
                msg,
                source_channel="whatsapp_auto_reply",
            )
            results["whatsapp"] = str(sent.get("status") or "sent")
        except Exception:
            logger.exception("Meet WhatsApp summary failed")
            results["whatsapp"] = "error"

    if settings.meet_auto_send_summary_slack and settings.slack_owner_user_id.strip():
        from tempa.channels.slack.formatting import prepare_slack_reply
        from tempa.channels.slack.outbound import _split_text, send_slack_message
        from tempa.channels.slack.outbound import open_dm_for_user

        msg = format_meeting_summary(
            title, minutes, meet_link=meet_link, for_slack=True, live_notes_excerpt=live_notes_excerpt
        )
        formatted = prepare_slack_reply(msg)
        try:
            channel_id = await open_dm_for_user(settings.slack_owner_user_id.strip())
            for idx, chunk in enumerate(_split_text(formatted)):
                sent = await send_slack_message(
                    channel_id,
                    chunk,
                    source_channel="slack_auto_reply",
                )
                if sent.get("status") not in ("sent", "pending"):
                    results["slack"] = str(sent.get("status") or "error")
                    break
            else:
                results["slack"] = "sent"
        except Exception:
            logger.exception("Meet Slack summary failed")
            results["slack"] = "error"

    return results
