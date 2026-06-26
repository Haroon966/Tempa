from __future__ import annotations

import pytest

from tempa.core.pending_actions import create_pending_action, execute_pending_action
from tempa.varys import harness


@pytest.fixture
def harness_db(tmp_path, monkeypatch):
    db_path = tmp_path / "harness.db"
    store = tmp_path / "pending_actions.json"
    monkeypatch.setenv("VARYS_HARNESS_DB", str(db_path))
    monkeypatch.setattr("tempa.core.pending_actions._store_path", lambda: store)
    from tempa.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_varys_ticket_pending_action_approves(harness_db):
    db = harness.get_db()
    try:
        ticket_id = harness.create_ticket(db, title="Fix oauth", origin_channel="dashboard")
    finally:
        db.close()

    action = create_pending_action(
        "varys_ticket",
        {"ticket_id": ticket_id, "title": "Fix oauth", "origin_channel": "dashboard"},
        source_channel="dashboard",
    )
    result = await execute_pending_action(action["id"])
    assert result["status"] == "executed"
    assert result["result"]["status"] == "approved"

    db = harness.get_db()
    try:
        ticket = harness.get_ticket(db, ticket_id)
        assert ticket["status"] == "in_progress"
        rows = db.execute("SELECT type FROM events WHERE type='message.go_signal'").fetchall()
        assert len(rows) == 1
    finally:
        db.close()
