"""Post-meeting follow-up draft generation."""

from __future__ import annotations

import json
import logging
from typing import Any

from tempa.core.pending_actions import create_pending_action
from tempa.meet.models import FollowUpDraft
from tempa.router.groq_router import get_router

logger = logging.getLogger(__name__)


async def generate_followup_drafts(
    minutes: dict[str, Any],
    *,
    title: str,
    attendee_emails: list[str],
    transcript_excerpt: str,
) -> list[dict[str, Any]]:
    if not minutes and not transcript_excerpt.strip():
        return []

    router = get_router()
    action_items = minutes.get("action_items") or []
    tldr = minutes.get("tldr") or minutes.get("summary") or ""
    attendees_str = ", ".join(attendee_emails) if attendee_emails else "unknown"

    prompt = (
        "Generate follow-up message drafts after a meeting. Return JSON array with objects:\n"
        '{ "channel": "email"|"whatsapp", "recipient": "email or phone", '
        '"recipient_name": "optional", "subject": "email only", "body": "...", "rationale": "..." }\n'
        "Include one recap email to all attendees (use first attendee email, mention others in body) "
        "and optional WhatsApp DMs for action item owners when identifiable.\n\n"
        f"Meeting: {title}\nAttendees: {attendees_str}\nTL;DR: {tldr}\n"
        f"Action items: {json.dumps(action_items)}\n\nTranscript excerpt:\n{transcript_excerpt[-6000:]}"
    )
    drafts: list[dict[str, Any]] = []
    try:
        response = router.chat_completion(
            category="reasoning",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
        )
        content = (response.choices[0].message.content or "").strip()
        start = content.find("[")
        end = content.rfind("]")
        if start >= 0 and end > start:
            raw_items = json.loads(content[start : end + 1])
            if isinstance(raw_items, list):
                for item in raw_items:
                    if not isinstance(item, dict):
                        continue
                    try:
                        draft = FollowUpDraft.model_validate(item)
                        drafts.append(draft.model_dump())
                    except Exception:
                        if item.get("body") and item.get("channel"):
                            drafts.append(item)
    except Exception:
        logger.exception("Follow-up LLM generation failed")

    if not drafts and attendee_emails and tldr:
        drafts.append(
            FollowUpDraft(
                channel="email",
                recipient=attendee_emails[0],
                recipient_name=None,
                subject=f"Recap: {title}",
                body=f"Hi all,\n\n{tldr}\n\nAction items:\n"
                + "\n".join(
                    f"- {(a.get('owner') or 'TBD')}: {a.get('task', '')}"
                    for a in action_items[:10]
                    if isinstance(a, dict)
                ),
                rationale="Default recap email from meeting minutes",
            ).model_dump()
        )
    return drafts


def create_followup_pending_actions(
    meeting_id: str,
    followups: list[dict[str, Any]],
    *,
    title: str = "",
) -> list[str]:
    pending_ids: list[str] = []
    for draft in followups:
        channel = draft.get("channel")
        if channel == "email":
            payload = {
                "to": draft.get("recipient", ""),
                "subject": draft.get("subject") or f"Follow-up: {title}",
                "body": draft.get("body", ""),
                "meeting_id": meeting_id,
            }
            action = create_pending_action(
                "email_send",
                payload,
                source_channel=f"meeting:{meeting_id}",
                title=f"Email: {payload['subject'][:60]}",
                risk_level="medium",
            )
        elif channel == "whatsapp":
            payload = {
                "number": draft.get("recipient", ""),
                "text": draft.get("body", ""),
                "meeting_id": meeting_id,
            }
            action = create_pending_action(
                "whatsapp_send",
                payload,
                source_channel=f"meeting:{meeting_id}",
                title=f"WhatsApp to {draft.get('recipient_name') or payload['number']}",
                risk_level="medium",
            )
        else:
            continue
        pending_ids.append(action["id"])
    return pending_ids
