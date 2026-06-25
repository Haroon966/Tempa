from __future__ import annotations

import logging
from typing import Any

from tempa.varys import harness
from tempa.varys.context import build_context
from tempa.varys.manager import build_dispatch_prompt
from tempa.varys.pollers import poll_all
from tempa.varys.runner import run_claude_prompt_sync

logger = logging.getLogger(__name__)


def run_dispatch() -> dict[str, Any]:
    db = harness.get_db()
    dispatched = 0
    errors: list[str] = []
    try:
        for context_key in harness.pending_context_keys(db):
            if harness.has_running_session(db, context_key):
                continue
            events = harness.pending_events_for_context(db, context_key)
            if not events:
                continue
            session_id = harness.create_session(
                db,
                context_key=context_key,
                intent=events[0].get("type", ""),
            )
            harness.mark_events_processing(db, context_key)
            try:
                prompt = build_dispatch_prompt(events)
                ctx = build_context(prompt, {"varys_dispatch": True})
                run_claude_prompt_sync(system=ctx["system"], user=ctx["user"])
                logger.info("Dispatched context_key=%s session=%s", context_key, session_id)
                dispatched += 1
                harness.complete_events(db, context_key)
                harness.finish_session(db, session_id, status="done")
            except Exception as exc:
                logger.exception("Dispatch failed for %s", context_key)
                errors.append(str(exc))
                harness.finish_session(db, session_id, status="cancelled")
    finally:
        db.close()
    return {"dispatched": dispatched, "errors": errors}


def run_tick() -> dict[str, Any]:
    from datetime import datetime, timezone

    db = harness.get_db()
    if not harness.acquire_tick_lock(db, "tempa-varys-tick"):
        db.close()
        return {"skipped": True, "reason": "lock_held"}
    try:
        poll_errors: list[str] = []
        try:
            poll_all()
        except Exception as exc:
            poll_errors.append(str(exc))
            logger.exception("Ticket poller failed")
            return {"aborted": True, "errors": poll_errors}

        result = run_dispatch()
        if not poll_errors:
            harness.set_last_sync_at(db, datetime.now(timezone.utc).isoformat())
        return {"aborted": False, "poll_errors": poll_errors, **result}
    finally:
        harness.release_tick_lock(db)
        db.close()
