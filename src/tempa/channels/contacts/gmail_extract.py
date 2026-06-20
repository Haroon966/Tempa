from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from tempa.channels.gmail.oauth import load_gmail_client

logger = logging.getLogger(__name__)

_HEADER_CONTACT_RE = re.compile(
    r'(?:"([^"]+)"|([^,<]+?))\s*<?([\w.\-+]+@[\w.\-]+\.\w+)>?'
)


def _parse_address_header(value: str) -> list[dict[str, str]]:
    contacts: list[dict[str, str]] = []
    if not value.strip():
        return contacts
    for part in re.split(r",(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", value):
        part = part.strip()
        if not part:
            continue
        match = _HEADER_CONTACT_RE.search(part)
        if match:
            name = (match.group(1) or match.group(2) or "").strip()
            email = match.group(3).strip().lower()
            contacts.append({"name": name, "email": email})
            continue
        bare = re.search(r"[\w.\-+]+@[\w.\-]+\.\w+", part)
        if bare:
            contacts.append({"name": "", "email": bare.group(0).lower()})
    return contacts


async def extract_contacts_from_gmail(*, max_messages: int = 500) -> dict[str, Any]:
    """Build a local contacts cache from Gmail From/To headers."""
    from tempa.channels.contacts.store import upsert_contacts

    client = load_gmail_client()
    if client is None:
        return {"status": "skipped", "reason": "Gmail not connected"}

    ids = await asyncio.to_thread(
        client.iter_message_ids,
        query="newer_than:2y",
        max_results=max_messages,
    )
    seen_emails: dict[str, dict[str, Any]] = {}
    scanned = 0
    for mid in ids:
        try:
            msg = await asyncio.to_thread(client.get_message_metadata, mid)
        except Exception:
            logger.debug("Skipping message %s during contact extract", mid)
            continue
        scanned += 1
        for header in (msg.sender, msg.to):
            for row in _parse_address_header(header):
                email = row["email"]
                if email in seen_emails:
                    if row["name"] and not seen_emails[email].get("name"):
                        seen_emails[email]["name"] = row["name"]
                    continue
                seen_emails[email] = {
                    "id": f"gmail:{email}",
                    "name": row["name"],
                    "email": email,
                    "phone": "",
                    "source": "gmail",
                }

    contacts = list(seen_emails.values())
    count = await upsert_contacts(contacts) if contacts else 0
    return {"status": "ok", "source": "gmail", "scanned_messages": scanned, "count": count}
