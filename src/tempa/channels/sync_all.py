from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from tempa.channels.contacts.gmail_extract import extract_contacts_from_gmail
from tempa.channels.contacts.sync import sync_contacts
from tempa.channels.gmail.oauth import load_gmail_client
from tempa.channels.gmail.sync import load_sync_state, save_sync_state, sync_once
from tempa.settings import get_settings

logger = logging.getLogger(__name__)


async def sync_gmail_backfill(*, max_messages: int = 500, query: str = "newer_than:2y") -> dict[str, Any]:
    """Ingest historical Gmail into RAG (full message bodies)."""
    from tempa.channels.gmail.ingest import ingest_gmail_message

    client = load_gmail_client()
    if client is None:
        return {"status": "skipped", "reason": "Gmail not connected"}

    state = load_sync_state()
    seen = set(state.get("seen_message_ids") or [])
    ids = await asyncio.to_thread(
        client.iter_message_ids,
        query=query,
        max_results=max_messages,
    )
    new_ids = [mid for mid in ids if mid not in seen]

    ingested = 0
    for mid in new_ids:
        try:
            msg = await asyncio.to_thread(client.get_message, mid)
            await asyncio.to_thread(ingest_gmail_message, msg, tags=["sync", "backfill"])
            seen.add(mid)
            ingested += 1
        except Exception:
            logger.exception("Failed to backfill message %s", mid)

    state["seen_message_ids"] = list(seen)[-10000:]
    state["last_sync_at"] = datetime.now(timezone.utc).isoformat()
    save_sync_state(state)
    return {
        "status": "ok",
        "queried": len(ids),
        "new_messages": ingested,
        "query": query,
    }


async def sync_calendar_to_memory(*, days_past: int = 30, days_future: int = 90) -> dict[str, Any]:
    """Ingest upcoming and recent calendar events into RAG."""
    import datetime as dt

    from tempa.channels.calendar.ingest import ingest_calendar_event
    from tempa.channels.calendar.oauth import load_calendar_client

    client = load_calendar_client()
    if client is None:
        return {"status": "skipped", "reason": "Google Calendar not connected"}

    now = dt.datetime.now(dt.timezone.utc)
    events = client.list_upcoming_events(
        calendar_id="primary",
        time_min=now - dt.timedelta(days=days_past),
        time_max=now + dt.timedelta(days=days_future),
        max_results=250,
    )
    ingested = 0
    for ev in events:
        try:
            ingest_calendar_event(ev)
            ingested += 1
        except Exception:
            logger.exception("Failed to ingest calendar event %s", ev.summary)
    return {"status": "ok", "events": ingested}


async def sync_all(
    *,
    max_emails: int = 500,
    email_query: str = "newer_than:2y",
    extract_gmail_contacts: bool = True,
) -> dict[str, Any]:
    """Sync contacts, Gmail history, and calendar into Tempa memory."""
    results: dict[str, Any] = {}

    contacts = await sync_contacts()
    results["google_contacts"] = contacts
    if contacts.get("status") != "ok" and extract_gmail_contacts:
        results["gmail_contacts"] = await extract_contacts_from_gmail(max_messages=max_emails)

    try:
        from tempa.channels.jira.sync import sync_jira_users

        results["jira_users"] = await sync_jira_users()
    except Exception as exc:
        results["jira_users"] = {"status": "error", "reason": str(exc)}

    try:
        from tempa.channels.contacts.linker import identity_link_count

        results["identity_link_count"] = identity_link_count()
    except Exception:
        results["identity_link_count"] = None

    results["gmail_incremental"] = await sync_once(full=True)
    results["gmail_backfill"] = await sync_gmail_backfill(max_messages=max_emails, query=email_query)
    results["calendar"] = await sync_calendar_to_memory()

    try:
        from tempa.channels.slack.sync import sync_once as sync_slack_once

        results["slack"] = await sync_slack_once(full=True)
    except Exception as exc:
        results["slack"] = {"status": "error", "reason": str(exc)}

    try:
        from tempa.rag.store import get_store

        results["rag_chunks"] = get_store().count()
    except Exception:
        results["rag_chunks"] = None

    try:
        from tempa.channels.contacts.store import contact_count

        results["contact_count"] = await contact_count()
    except Exception:
        results["contact_count"] = None

    results["status"] = "ok"
    results["data_dir"] = str(get_settings().tempa_data_dir)
    return results
