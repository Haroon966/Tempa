from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tempa.varys import harness


@pytest.fixture
def harness_db(tmp_path, monkeypatch):
    db_path = tmp_path / "harness.db"
    monkeypatch.setenv("VARYS_HARNESS_DB", str(db_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    yield db_path
    get_settings.cache_clear()


def test_tick_lock_exclusive(harness_db):
    db = harness.get_db()
    try:
        assert harness.acquire_tick_lock(db, "test-a") is True
        assert harness.acquire_tick_lock(db, "test-b") is False
        harness.release_tick_lock(db)
        assert harness.acquire_tick_lock(db, "test-c") is True
        harness.release_tick_lock(db)
    finally:
        db.close()


def test_event_idempotency(harness_db):
    db = harness.get_db()
    try:
        entity = harness.register_entity(db, "tempa", "t1", "ticket")
        first = harness.insert_event(
            db,
            event_id="tempa-t1",
            source="tempa",
            event_type="ticket.created",
            context_key=entity,
            payload={"id": "t1"},
        )
        second = harness.insert_event(
            db,
            event_id="tempa-t1",
            source="tempa",
            event_type="ticket.created",
            context_key=entity,
            payload={"id": "t1"},
        )
        assert first is True
        assert second is False
        pending = harness.pending_context_keys(db)
        assert entity in pending
    finally:
        db.close()


def test_create_ticket_mints_event(harness_db):
    db = harness.get_db()
    try:
        ticket_id = harness.create_ticket(db, title="Fix login bug", origin_channel="slack")
        assert ticket_id.startswith("ticket-")
        keys = harness.pending_context_keys(db)
        assert len(keys) == 1
        events = harness.pending_events_for_context(db, keys[0])
        assert events[0]["type"] == "ticket.created"
        assert events[0]["payload"]["title"] == "Fix login bug"
    finally:
        db.close()
