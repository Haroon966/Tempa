from __future__ import annotations

import logging

from tempa.settings import get_settings
from tempa.varys import harness
from tempa.varys.notion.client import notion_configured

logger = logging.getLogger(__name__)


def poll_open_tickets() -> int:
    """Enqueue ticket.created events for open tickets without pending events."""
    db = harness.get_db()
    new_events = 0
    try:
        rows = db.execute(
            "SELECT id, title, status FROM tickets WHERE status IN ('open', 'in_progress')"
        ).fetchall()
        for row in rows:
            ticket_id, title, status = row[0], row[1], row[2]
            entity_id = harness.register_entity(db, "tempa", ticket_id, "ticket", f"tempa:{ticket_id}")
            event_id = f"tempa-{ticket_id}"
            if harness.insert_event(
                db,
                event_id=event_id,
                source="tempa",
                event_type="ticket.created",
                context_key=entity_id,
                payload={"id": ticket_id, "title": title, "status": status},
            ):
                new_events += 1
    finally:
        db.close()
    return new_events


def poll_notion_harness() -> int:
    """Placeholder for Notion Harness DB poller — enabled when notion_configured()."""
    if not notion_configured():
        return 0
    logger.debug("Notion harness poller not yet implemented; skipping")
    return 0


def poll_github_repos() -> int:
    """Placeholder for configured repo PR poller."""
    settings = get_settings()
    from tempa.varys.config import load_varys_config

    cfg = load_varys_config()
    if not cfg.repos and not settings.github_app_id:
        return 0
    logger.debug("GitHub varys poller not yet implemented; skipping")
    return 0


def poll_all() -> dict[str, int]:
    return {
        "tickets": poll_open_tickets(),
        "notion": poll_notion_harness(),
        "github": poll_github_repos(),
    }
