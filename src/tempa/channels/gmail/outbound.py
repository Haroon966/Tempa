from __future__ import annotations

import asyncio
import logging

from tempa.channels.gmail.ingest import ingest_sent_email
from tempa.channels.gmail.oauth import load_gmail_client
from tempa.core.events import event_bus
from tempa.router.safety import screen_outbound_message

logger = logging.getLogger(__name__)


async def send_gmail_message(
    *,
    to: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    cc: str = "",
    bcc: str = "",
    skip_safety: bool = False,
) -> dict:
    from tempa.channels.gmail.session_state import record_gmail_action

    client = load_gmail_client()
    if client is None:
        result = {"status": "error", "reason": "Gmail not connected", "to": to}
        record_gmail_action(result)
        return result

    full_text = f"To: {to}\nSubject: {subject}\n\n{body}"
    if html_body:
        full_text += f"\n\n[HTML body length: {len(html_body)} chars]"
    if skip_safety:
        allowed, reason = True, "skipped"
    else:
        allowed, reason = await asyncio.to_thread(screen_outbound_message, full_text)
    if not allowed:
        await event_bus.publish_json("gmail", "blocked", reason[:120])
        result = {"status": "blocked", "reason": reason or "blocked by safety screen", "to": to}
        record_gmail_action(result)
        return result

    try:
        result = await asyncio.to_thread(
            client.send_message,
            to=to,
            subject=subject,
            body=body,
            html_body=html_body,
            cc=cc,
            bcc=bcc,
        )
    except Exception as exc:
        logger.exception("Gmail send failed")
        result = {"status": "error", "reason": str(exc) or "Gmail API error", "to": to}
        record_gmail_action(result)
        return result

    message_id = str(result.get("id", ""))
    thread_id = str(result.get("threadId", ""))
    asyncio.create_task(
        asyncio.to_thread(
            ingest_sent_email,
            to=to,
            subject=subject,
            body=html_body or body,
            message_id=message_id,
            thread_id=thread_id,
        )
    )
    await event_bus.publish_json("gmail", "sent", to)
    sent = {
        "status": "sent",
        "message_id": message_id,
        "thread_id": thread_id,
        "to": to,
        "html": bool(html_body),
    }
    record_gmail_action(sent)
    return sent
