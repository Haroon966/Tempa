from __future__ import annotations

from tempa.channels.gmail.client import GmailMessage
from tempa.rag.ingest import ingest_text


def message_to_text(msg: GmailMessage) -> str:
    parts = [
        f"Subject: {msg.subject}",
        f"From: {msg.sender}",
        f"To: {msg.to}",
        f"Date: {msg.date}",
    ]
    if msg.snippet and msg.snippet not in (msg.body_text or ""):
        parts.append(f"Snippet: {msg.snippet}")
    if msg.body_text:
        parts.append(msg.body_text)
    elif msg.snippet:
        parts.append(msg.snippet)
    return "\n".join(parts)


def ingest_gmail_message(msg: GmailMessage, *, tags: list[str] | None = None) -> dict:
    text = message_to_text(msg)
    participants = [p for p in (msg.sender, msg.to) if p]
    tag_list = list(tags or ["inbound"])
    return ingest_text(
        text,
        tool="gmail",
        source=f"thread:{msg.thread_id}",
        participants=participants,
        tags=tag_list + [f"msg:{msg.id}"],
        title=msg.subject,
    )


def ingest_sent_email(
    *,
    to: str,
    subject: str,
    body: str,
    message_id: str = "",
    thread_id: str = "",
) -> dict:
    text = f"Subject: {subject}\nTo: {to}\n\n{body}"
    source = f"thread:{thread_id}" if thread_id else f"sent:{message_id or 'draft'}"
    return ingest_text(
        text,
        tool="gmail",
        source=source,
        participants=[to],
        tags=["outbound", f"msg:{message_id}"] if message_id else ["outbound"],
        title=subject,
    )
