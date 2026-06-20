from __future__ import annotations

import pytest

from tempa.core.pending_actions import (
    create_pending_action,
    execute_pending_action,
    list_pending_actions,
    reject_pending_action,
)
from tempa.core.task_store import complete_task, create_task, list_active_tasks


@pytest.fixture(autouse=True)
def isolated_pending_store(tmp_path, monkeypatch):
    store = tmp_path / "pending_actions.json"
    monkeypatch.setattr("tempa.core.pending_actions._store_path", lambda: store)
    yield


@pytest.fixture
def isolated_task_store(tmp_path, monkeypatch):
    status = tmp_path / "tasks" / "task_status.json"
    monkeypatch.setattr("tempa.core.task_store._status_path", lambda: status)
    yield


def test_create_and_list_pending():
    action = create_pending_action("email_send", {"to": "a@b.com", "subject": "Hi", "body": "Hello"})
    assert action["status"] == "pending"
    pending = list_pending_actions(status="pending")
    assert len(pending) == 1
    assert pending[0]["id"] == action["id"]


def test_reject_pending():
    action = create_pending_action("pc_write", {"path": "/tmp/x", "content": "y"})
    rejected = reject_pending_action(action["id"])
    assert rejected is not None
    assert rejected["status"] == "rejected"
    assert list_pending_actions(status="pending") == []


@pytest.mark.asyncio
async def test_execute_idempotent(monkeypatch):
    async def fake_send(**kwargs):
        return {"status": "sent", "to": kwargs["to"]}

    monkeypatch.setattr("tempa.channels.gmail.outbound.send_gmail_message", fake_send)
    action = create_pending_action("email_send", {"to": "a@b.com", "subject": "Hi", "body": "Hello"})
    first = await execute_pending_action(action["id"])
    assert first["status"] == "executed"
    second = await execute_pending_action(action["id"])
    assert second.get("idempotent") is True


def test_task_store_lifecycle(isolated_task_store):
    task_id = create_task("Do something", [{"agent": "pc", "task": "write file"}])
    active = list_active_tasks()
    assert any(t["id"] == task_id for t in active)
    complete_task(task_id)
    assert not any(t["id"] == task_id for t in list_active_tasks())
