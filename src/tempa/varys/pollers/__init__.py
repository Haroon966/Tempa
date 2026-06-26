from __future__ import annotations

import logging

from tempa.settings import get_settings
from tempa.varys import harness
from tempa.varys.notion.client import notion_configured, query_harness_database
from tempa.varys.pollers import github as github_poller
from tempa.varys.pollers import jira as jira_poller

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
    """Poll Notion harness DB for pages edited since last sync."""
    if not notion_configured():
        return 0
    settings = get_settings()
    if not settings.notion_enabled:
        from tempa.varys.config import load_varys_config

        if not load_varys_config().notion_enabled:
            return 0

    db = harness.get_db()
    new_events = 0
    try:
        since = harness.get_last_sync_at(db)
        pages = query_harness_database(since_iso=since)
        for page in pages:
            page_id = str(page.get("id") or "")
            if not page_id:
                continue
            entity_id = harness.register_entity(
                db,
                "notion",
                page_id,
                "page",
                str(page.get("url") or ""),
            )
            event_id = f"notion-{page_id}-{str(page.get('last_edited_time') or '').replace(':', '')}"
            if harness.insert_event(
                db,
                event_id=event_id,
                source="notion",
                event_type="notion.page_updated",
                context_key=entity_id,
                payload=page,
            ):
                new_events += 1
    except Exception as exc:
        logger.exception("Notion harness poller failed: %s", exc)
    finally:
        db.close()
    return new_events


def poll_jira_issues() -> int:
    """Poll Jira for issues updated since last sync."""
    from tempa.channels.jira.client import jira_enabled

    if not jira_enabled():
        return 0

    db = harness.get_db()
    new_events = 0
    try:
        since = harness.get_last_sync_at(db)
        issues = jira_poller.poll_repos(since)
        for issue in issues:
            issue_key = str(issue.get("key") or "")
            if not issue_key:
                continue
            entity_id = harness.register_entity(
                db,
                "jira",
                issue_key,
                "issue",
                str(issue.get("url") or ""),
            )
            event_id = (
                f"jira-{issue_key}-{str(issue.get('updated') or '').replace(':', '')}"
            )
            if harness.insert_event(
                db,
                event_id=event_id,
                source="jira",
                event_type="jira.issue_updated",
                context_key=entity_id,
                payload=issue,
            ):
                new_events += 1
    except Exception as exc:
        logger.exception("Jira harness poller failed: %s", exc)
    finally:
        db.close()
    return new_events


def poll_github_repos() -> int:
    """Poll configured repos for PRs updated since last sync."""
    from tempa.qa.github.auth import github_configured
    from tempa.varys.config import load_varys_config

    cfg = load_varys_config()
    if not cfg.repos or not github_configured():
        return 0

    db = harness.get_db()
    new_events = 0
    try:
        since = harness.get_last_sync_at(db)
        pulls = github_poller.poll_repos(since)
        for pr in pulls:
            repo = str(pr.get("repo") or "")
            number = pr.get("number")
            if not repo or number is None:
                continue
            external_id = f"{repo}#{number}"
            entity_id = harness.register_entity(
                db,
                "github",
                external_id,
                "pull_request",
                str(pr.get("url") or ""),
            )
            event_id = (
                f"github-{repo.replace('/', '-')}-{number}-"
                f"{str(pr.get('updated_at') or '').replace(':', '')}"
            )
            if harness.insert_event(
                db,
                event_id=event_id,
                source="github",
                event_type="github.pr_updated",
                context_key=entity_id,
                payload=pr,
            ):
                new_events += 1
    except Exception as exc:
        logger.exception("GitHub varys poller failed: %s", exc)
    finally:
        db.close()
    return new_events


def poll_all() -> dict[str, int]:
    return {
        "tickets": poll_open_tickets(),
        "notion": poll_notion_harness(),
        "github": poll_github_repos(),
        "jira": poll_jira_issues(),
    }
