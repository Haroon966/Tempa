from __future__ import annotations

import html
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _normalize_title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())


def is_punjab_daily_sync(title: str) -> bool:
    return _normalize_title_key(title) == "teampunjabdailysync"


def _meeting_tldr(minutes: dict[str, Any], live_notes_excerpt: str = "") -> str:
    summary = str(minutes.get("tldr") or minutes.get("summary") or "").strip()
    if not summary and live_notes_excerpt.strip():
        summary = live_notes_excerpt.strip()[:2000]
    return summary or "Meeting completed — see live notes and transcript in Tempa dashboard."


def _decision_lines(minutes: dict[str, Any], *, limit: int = 4) -> list[str]:
    lines: list[str] = []
    for item in (minutes.get("decisions") or [])[:limit]:
        if isinstance(item, dict):
            text = str(item.get("summary") or item.get("text") or "").strip()
        else:
            text = str(item).strip()
        if text:
            lines.append(text)
    return lines


def _action_item_lines(minutes: dict[str, Any], *, limit: int = 6) -> list[str]:
    lines: list[str] = []
    for item in (minutes.get("action_items") or [])[:limit]:
        if isinstance(item, dict):
            owner = str(item.get("owner") or "Unassigned").strip()
            task = str(item.get("task") or "").strip()
            due = str(item.get("due") or "").strip()
            line = f"{owner}: {task}" if task else owner
            if due:
                line += f" (due {due})"
            if line.strip(":"):
                lines.append(line)
        else:
            text = str(item).strip()
            if text:
                lines.append(text)
    return lines


def _open_question_lines(minutes: dict[str, Any], *, limit: int = 3) -> list[str]:
    lines: list[str] = []
    for item in (minutes.get("open_questions") or [])[:limit]:
        if isinstance(item, dict):
            q = str(item.get("question") or "").strip()
        else:
            q = str(item).strip()
        if q:
            lines.append(q)
    return lines


def _highlight_lines(minutes: dict[str, Any], *, limit: int = 5) -> list[str]:
    lines: list[str] = []
    for point in (minutes.get("highlights") or minutes.get("key_points") or [])[:limit]:
        text = str(point).strip()
        if text:
            lines.append(text)
    return lines


def format_meeting_summary(
    title: str,
    minutes: dict[str, Any],
    *,
    meet_link: str = "",
    youtube_url: str = "",
    for_slack: bool = False,
    live_notes_excerpt: str = "",
) -> str:
    """Build a rich post-meeting summary for Slack (mrkdwn) or email/WhatsApp."""
    bold = "*" if for_slack else "*"
    summary = _meeting_tldr(minutes, live_notes_excerpt)
    lines = [f"{bold}{title}{bold} ended.", "", summary]

    decisions = _decision_lines(minutes)
    if decisions:
        lines.append("")
        lines.append(f"{bold}Decisions{bold}")
        lines.extend(f"• {text}" for text in decisions)

    action_items = _action_item_lines(minutes)
    if action_items:
        lines.append("")
        lines.append(f"{bold}Action items{bold}")
        lines.extend(f"• {text}" for text in action_items)

    open_qs = _open_question_lines(minutes)
    if open_qs:
        lines.append("")
        lines.append(f"{bold}Open questions{bold}")
        lines.extend(f"• {q}" for q in open_qs)

    highlights = _highlight_lines(minutes)
    if highlights:
        lines.append("")
        lines.append(f"{bold}Highlights{bold}")
        lines.extend(f"• {point}" for point in highlights)

    if meet_link:
        lines.append("")
        lines.append(f"Link: {meet_link}")

    youtube_url = str(youtube_url or "").strip()
    if youtube_url:
        lines.append("")
        lines.append(f"YouTube: {youtube_url}")

    lines.append("")
    lines.append("Full transcript and minutes are in the Tempa dashboard.")
    text = "\n".join(lines)
    return text[:3900] if for_slack else text[:3500]


def _youtube_video_id(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    patterns = (
        r"(?:youtube\.com/watch\?[^#]*v=|youtube\.com/embed/|youtube\.com/live/|youtu\.be/)([A-Za-z0-9_-]{6,})",
        r"youtube\.com/shorts/([A-Za-z0-9_-]{6,})",
    )
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            return match.group(1)
    return ""


def _email_section(title: str, rows_html: str, *, accent: str, tint: str) -> str:
    if not rows_html.strip():
        return ""
    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 18px;">
        <tr>
          <td style="padding:0 0 8px;">
            <span style="display:inline-block;font-family:Arial,Helvetica,sans-serif;font-size:11px;
              font-weight:bold;letter-spacing:1.2px;text-transform:uppercase;color:{accent};">
              {html.escape(title)}
            </span>
          </td>
        </tr>
        <tr>
          <td>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
              style="background-color:{tint};border-radius:10px;border-left:4px solid {accent};">
              <tr>
                <td style="padding:16px 18px 6px;">
                  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                    {rows_html}
                  </table>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>"""


def _bullet_rows(items: list[str], *, accent: str) -> str:
    return "".join(
        f'<tr>'
        f'<td valign="top" style="padding:0 10px 12px 0;font-family:Arial,Helvetica,sans-serif;'
        f'font-size:15px;line-height:1.5;color:{accent};width:18px;">&#8226;</td>'
        f'<td style="padding:0 0 12px;font-family:Arial,Helvetica,sans-serif;'
        f'font-size:15px;line-height:1.55;color:#243044;">{html.escape(item)}</td>'
        f"</tr>"
        for item in items
    )


def _action_item_rows(minutes: dict[str, Any], *, limit: int = 6) -> str:
    rows: list[str] = []
    items = list(minutes.get("action_items") or [])[:limit]
    for index, item in enumerate(items):
        if isinstance(item, dict):
            owner = str(item.get("owner") or "Unassigned").strip()
            task = str(item.get("task") or "").strip()
            due = str(item.get("due") or "").strip()
        else:
            owner, task, due = "Unassigned", str(item).strip(), ""
        if not (owner or task):
            continue
        due_badge = ""
        if due:
            due_badge = (
                f' <span style="display:inline-block;padding:2px 8px;border-radius:999px;'
                f'background-color:#FEF3C7;font-family:Arial,Helvetica,sans-serif;font-size:11px;'
                f'font-weight:bold;letter-spacing:0.3px;color:#B45309;vertical-align:middle;">'
                f"due {html.escape(due)}</span>"
            )
        top_pad = "0" if index == 0 else "4px"
        rows.append(
            f'<tr>'
            f'<td valign="top" style="padding:{top_pad} 10px 12px 0;font-family:Arial,Helvetica,sans-serif;'
            f'font-size:15px;line-height:1.5;color:#D97706;width:18px;">&#8226;</td>'
            f'<td style="padding:{top_pad} 0 12px;font-family:Arial,Helvetica,sans-serif;'
            f'font-size:15px;line-height:1.55;color:#243044;">'
            f'<span style="font-weight:bold;color:#92400E;">{html.escape(owner)}</span>'
            f"{due_badge}"
            f'<br><span style="color:#243044;">{html.escape(task or "Follow up")}</span>'
            f"</td></tr>"
        )
    return "".join(rows)


def _video_hero_html(*, youtube_url: str, title: str, thumb_src: str = "") -> str:
    """Email-safe video hero: 16:9 thumbnail + play CTA (clients cannot autoplay embeds)."""
    video_id = _youtube_video_id(youtube_url)
    safe_url = html.escape(youtube_url, quote=True)
    safe_title = html.escape(title or "Meeting recording")
    # 552×311 ≈ 16:9 inside the email card padding.
    frame_w, frame_h = 552, 311

    if video_id or thumb_src.strip():
        # Prefer CID (inline) so Gmail shows the thumb without "Display images".
        # Fall back to YouTube CDN (hqdefault is more compatible than maxres).
        remote = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else ""
        thumb = html.escape((thumb_src or remote).strip(), quote=True)
        return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0;">
        <tr>
          <td style="padding:0 0 12px;">
            <span style="display:inline-block;background-color:#FEE2E2;color:#B91C1C;font-family:Arial,Helvetica,sans-serif;
              font-size:11px;font-weight:bold;letter-spacing:1px;text-transform:uppercase;padding:5px 10px;border-radius:999px;">
              Meeting video
            </span>
          </td>
        </tr>
        <tr>
          <td style="border-radius:14px;overflow:hidden;background-color:#0F172A;">
            <a href="{safe_url}" target="_blank" style="text-decoration:none;display:block;line-height:0;">
              <img src="{thumb}" width="{frame_w}" height="{frame_h}" alt="Play recording: {safe_title}"
                style="display:block;width:100%;max-width:{frame_w}px;height:{frame_h}px;object-fit:cover;border:0;border-radius:14px 14px 0 0;background-color:#0F172A;">
            </a>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
              style="background-color:#4F46E5;">
              <tr>
                <td align="center" bgcolor="#4F46E5" style="padding:16px 18px;background-color:#4F46E5;">
                  <a href="{safe_url}" target="_blank"
                    style="display:inline-block;padding:12px 26px;border-radius:999px;background-color:#FF0000;
                    font-family:Arial,Helvetica,sans-serif;font-size:15px;font-weight:bold;color:#FFFFFF;text-decoration:none;">
                    &#9654;&nbsp; Watch meeting video
                  </a>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>"""

    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0;">
        <tr>
          <td align="center" height="{frame_h}" style="height:{frame_h}px;padding:0;border-radius:14px;
            background-color:#4F46E5;">
            <a href="{safe_url}" target="_blank"
              style="display:inline-block;padding:14px 28px;border-radius:999px;background-color:#FFFFFF;
              font-family:Arial,Helvetica,sans-serif;font-size:15px;font-weight:bold;color:#4F46E5;text-decoration:none;">
              &#9654;&nbsp; Watch meeting video
            </a>
          </td>
        </tr>
      </table>"""


def _fetch_youtube_thumb_bytes(video_id: str) -> bytes | None:
    """Download a YouTube poster frame for CID embedding (Gmail-safe)."""
    if not video_id:
        return None
    import urllib.error
    import urllib.request

    for name in ("maxresdefault.jpg", "sddefault.jpg", "hqdefault.jpg"):
        url = f"https://i.ytimg.com/vi/{video_id}/{name}"
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = resp.read()
            # YouTube sometimes returns a tiny grey 120x90 placeholder with HTTP 200.
            if data and len(data) > 5000:
                return data
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    return None


def _slack_app_link() -> str:
    """Deep-link into the Tempa Slack workspace/app when tokens are configured."""
    try:
        from tempa.channels.slack.client import auth_test, load_slack_client

        client = load_slack_client()
        if client is None:
            return "https://app.slack.com/"
        data = auth_test(client) or {}
        team_id = str(data.get("team_id") or "").strip()
        workspace_url = str(data.get("url") or "").strip().rstrip("/")
        bot_user_id = str(data.get("user_id") or "").strip()
        if team_id and bot_user_id:
            # Opens the bot conversation in the Slack client when possible.
            return f"https://app.slack.com/client/{team_id}/{bot_user_id}"
        if team_id:
            return f"https://app.slack.com/client/{team_id}"
        if workspace_url:
            return workspace_url
    except Exception:
        logger.debug("Slack app link lookup failed", exc_info=True)
    return "https://app.slack.com/"


def _video_placeholder_html() -> str:
    return """
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0;">
        <tr>
          <td align="center" height="311" style="height:311px;padding:0;border-radius:14px;
            background-color:#6366F1;">
            <p style="margin:0 0 8px;font-family:Arial,Helvetica,sans-serif;font-size:28px;line-height:1;">&#127909;</p>
            <p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:15px;font-weight:bold;color:#FFFFFF;">
              Recording will appear here when ready
            </p>
          </td>
        </tr>
      </table>"""


def build_meeting_summary_email(
    title: str,
    minutes: dict[str, Any],
    *,
    meet_link: str = "",
    youtube_url: str = "",
    live_notes_excerpt: str = "",
    for_preview: bool = False,
) -> dict[str, Any]:
    """Build HTML + CID inline images for Gmail (footer bg + video thumb)."""
    from datetime import date

    from tempa.channels.gmail.compose import (
        FOOTER_BG_CID,
        VIDEO_THUMB_CID,
        build_brand_footer_html,
        build_html_email,
        email_footer_background_url,
        load_email_footer_bg_bytes,
    )
    from tempa.settings import get_settings

    summary = _meeting_tldr(minutes, live_notes_excerpt)
    meet_link = str(meet_link or "").strip()
    youtube_url = str(youtube_url or "").strip()
    safe_title = title or "Meeting notes"
    inline_images: list[tuple[str, bytes, str]] = []

    video_id = _youtube_video_id(youtube_url)
    thumb_src = ""
    if youtube_url and video_id:
        thumb_bytes = None if for_preview else _fetch_youtube_thumb_bytes(video_id)
        if thumb_bytes:
            inline_images.append((VIDEO_THUMB_CID, thumb_bytes, "jpeg"))
            thumb_src = f"cid:{VIDEO_THUMB_CID}"
        else:
            thumb_src = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        hero = _video_hero_html(youtube_url=youtube_url, title=safe_title, thumb_src=thumb_src)
    else:
        hero = _video_placeholder_html()

    status_row = """
      <p style="margin:0 0 18px;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.4;color:#475569;">
        <span style="display:inline-block;padding:4px 10px;border-radius:999px;background-color:#DCFCE7;
          font-weight:bold;letter-spacing:0.4px;text-transform:uppercase;font-size:11px;color:#15803D;">Ended</span>
        <span style="margin-left:8px;">Meeting notes are ready.</span>
      </p>"""

    summary_rows = (
        f'<tr><td style="padding:0 0 10px;font-family:Arial,Helvetica,sans-serif;'
        f'font-size:15px;line-height:1.65;color:#243044;">{html.escape(summary)}</td></tr>'
    )

    sections = [
        status_row,
        _email_section("Summary", summary_rows, accent="#0D9488", tint="#F0FDFA"),
        _email_section(
            "Decisions",
            _bullet_rows(_decision_lines(minutes), accent="#4F46E5"),
            accent="#4F46E5",
            tint="#EEF2FF",
        ),
        _email_section(
            "Action items",
            _action_item_rows(minutes),
            accent="#D97706",
            tint="#FFFBEB",
        ),
        _email_section(
            "Open questions",
            _bullet_rows(_open_question_lines(minutes), accent="#DB2777"),
            accent="#DB2777",
            tint="#FDF2F8",
        ),
        _email_section(
            "Highlights",
            _bullet_rows(_highlight_lines(minutes), accent="#2563EB"),
            accent="#2563EB",
            tint="#EFF6FF",
        ),
    ]
    body_html = "".join(part for part in sections if part)

    if meet_link:
        safe_meet = html.escape(meet_link, quote=True)
        body_html += f"""
      <p style="margin:0 0 8px;font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.5;color:#64748B;">
        Meet link:
        <a href="{safe_meet}" style="color:#4F46E5;text-decoration:underline;word-break:break-all;">{html.escape(meet_link)}</a>
      </p>"""

    settings = get_settings()
    base = settings.resolve_public_base_url()

    footer_bytes = load_email_footer_bg_bytes()
    if footer_bytes and not for_preview:
        inline_images.append((FOOTER_BG_CID, footer_bytes, "jpeg"))
    footer_bg = email_footer_background_url(for_preview=for_preview)

    footer = build_brand_footer_html(
        brand_name="Tempa",
        tagline="Your AI teammate for meetings, mail, and work.",
        links=(
            ("Mail", f"{base}/inbox/mail"),
            ("Slack", _slack_app_link()),
        ),
        copyright_text=f"© {date.today().year} Tempa.",
        credit_name="Haroon Ali",
        credit_url="https://github.com/Haroon966",
        unsubscribe_url="",
        background_url=footer_bg,
    )

    html_out = build_html_email(
        headline=safe_title,
        body_html=body_html,
        preview_text=summary[:90],
        eyebrow_label="" if youtube_url else "MEETING NOTES",
        eyebrow_bg="#EEF2FF",
        eyebrow_color="#4338CA",
        hero_html=hero,
        cta_url="",
        cta_label="",
        closing_text="Full transcript and minutes are available in the Tempa dashboard.",
        signature="",
        footer_html=footer,
    )
    return {
        "html": html_out,
        "inline_images": inline_images,
        "subject": f"Meeting notes: {safe_title}",
    }


def build_meeting_summary_html(
    title: str,
    minutes: dict[str, Any],
    *,
    meet_link: str = "",
    youtube_url: str = "",
    live_notes_excerpt: str = "",
    for_preview: bool = False,
) -> str:
    """HTML-only helper (preview/tests). Prefer build_meeting_summary_email for sends."""
    return str(
        build_meeting_summary_email(
            title,
            minutes,
            meet_link=meet_link,
            youtube_url=youtube_url,
            live_notes_excerpt=live_notes_excerpt,
            for_preview=for_preview,
        )["html"]
    )


async def _send_slack_dm(user_id: str, msg: str) -> str:
    from tempa.channels.slack.formatting import prepare_slack_reply
    from tempa.channels.slack.outbound import _split_text, open_dm_for_user, send_slack_message

    formatted = prepare_slack_reply(msg)
    channel_id = await open_dm_for_user(user_id.strip())
    for chunk in _split_text(formatted):
        sent = await send_slack_message(channel_id, chunk, source_channel="slack_auto_reply")
        if sent.get("status") not in ("sent", "pending"):
            return str(sent.get("status") or "error")
    return "sent"


def find_slack_user_id_by_email(email: str) -> str | None:
    """Resolve Slack user id from email (needs users:read.email)."""
    cleaned = (email or "").strip()
    if not cleaned or "@" not in cleaned:
        return None
    try:
        from tempa.channels.slack.client import load_slack_client

        client = load_slack_client()
        if client is None:
            return None
        resp = client.users_lookupByEmail(email=cleaned)
        user = (resp or {}).get("user") or {}
        uid = str(user.get("id") or "").strip()
        return uid or None
    except Exception:
        logger.debug("Slack lookupByEmail failed for %s", cleaned, exc_info=True)
        return None


async def _send_email_summary(
    *,
    to: str,
    title: str,
    body: str,
    html_body: str = "",
    inline_images: list | None = None,
) -> str:
    from tempa.channels.gmail.outbound import send_gmail_message

    try:
        sent = await send_gmail_message(
            to=to,
            subject=f"Meeting notes: {title}",
            body=body,
            html_body=html_body or None,
            skip_safety=True,
            inline_images=inline_images or (),
        )
        return str(sent.get("status") or "sent")
    except Exception:
        logger.exception("Meet email summary failed for %s", to)
        return "error"


def _summary_email_recipients(record: dict[str, Any]) -> list[str]:
    """Organizer + calendar owner, deduped."""
    emails: list[str] = []
    organizer = str(record.get("organizer_email") or "").strip().lower()
    if organizer and "@" in organizer:
        emails.append(organizer)
    try:
        from tempa.channels.calendar.events import get_calendar_owner_email

        owner = (get_calendar_owner_email() or "").strip().lower()
        if owner and "@" in owner and owner not in emails:
            emails.append(owner)
    except Exception:
        logger.debug("Calendar owner email lookup failed", exc_info=True)
    return emails


async def notify_meeting_completed(
    record: dict[str, Any],
    minutes: dict[str, Any],
    *,
    notify_number: str | None = None,
    live_notes_excerpt: str = "",
) -> dict[str, str]:
    """Send post-meeting notes to organizer + owner via Slack DM and email only."""
    from tempa.settings import get_settings

    settings = get_settings()
    title = str(record.get("title") or "Meeting")
    meet_link = str(record.get("meet_link") or "")
    youtube_url = str(record.get("youtube_url") or "")
    results: dict[str, str] = {}

    # WhatsApp kept behind flag for opt-in only (default off).
    if notify_number and settings.meet_auto_send_summary_whatsapp:
        from tempa.channels.whatsapp.outbound import send_whatsapp_message

        msg = format_meeting_summary(
            title,
            minutes,
            meet_link=meet_link,
            youtube_url=youtube_url,
            for_slack=False,
            live_notes_excerpt=live_notes_excerpt,
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

    slack_msg = format_meeting_summary(
        title,
        minutes,
        meet_link=meet_link,
        youtube_url=youtube_url,
        for_slack=True,
        live_notes_excerpt=live_notes_excerpt,
    )
    email_msg = format_meeting_summary(
        title,
        minutes,
        meet_link=meet_link,
        youtube_url=youtube_url,
        for_slack=False,
        live_notes_excerpt=live_notes_excerpt,
    )
    email_pack = build_meeting_summary_email(
        title,
        minutes,
        meet_link=meet_link,
        youtube_url=youtube_url,
        live_notes_excerpt=live_notes_excerpt,
    )
    email_html = str(email_pack["html"])
    email_inline = list(email_pack.get("inline_images") or [])

    if settings.meet_auto_send_summary_slack:
        slack_ids: list[str] = []
        owner_id = settings.slack_owner_user_id.strip()
        if owner_id:
            slack_ids.append(owner_id)
        organizer_email = str(record.get("organizer_email") or "").strip()
        if organizer_email:
            org_uid = find_slack_user_id_by_email(organizer_email)
            if org_uid and org_uid not in slack_ids:
                slack_ids.append(org_uid)
        slack_statuses: list[str] = []
        for uid in slack_ids:
            try:
                status = await _send_slack_dm(uid, slack_msg)
                slack_statuses.append(status)
            except Exception:
                logger.exception("Meet Slack summary failed for %s", uid)
                slack_statuses.append("error")
        if slack_statuses:
            results["slack"] = "sent" if all(s in ("sent", "pending") for s in slack_statuses) else (
                slack_statuses[0] if len(slack_statuses) == 1 else "partial"
            )
        elif owner_id:
            results["slack"] = "skipped"

    if settings.meet_auto_send_summary_email:
        recipients = _summary_email_recipients(record)
        email_statuses: list[str] = []
        for to in recipients:
            status = await _send_email_summary(
                to=to,
                title=title,
                body=email_msg,
                html_body=email_html,
                inline_images=email_inline,
            )
            email_statuses.append(status)
            results[f"email:{to}"] = status
        if email_statuses:
            results["email"] = (
                "sent"
                if all(s in ("sent", "pending") for s in email_statuses)
                else ("partial" if any(s in ("sent", "pending") for s in email_statuses) else "error")
            )

    return results
