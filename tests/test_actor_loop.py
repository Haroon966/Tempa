from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tempa.agents.graph import collect_pending_from_results
from tempa.core.cross_channel_conversation import enrich_conversation_context
from tempa.orchestrator.actor_loop import (
    needs_pause,
    run_actor_loop,
    should_use_actor_loop,
)


@pytest.fixture
def chat_store(tmp_path: Path, monkeypatch):
    from tempa.core import chat_sessions as cs

    sessions = tmp_path / "sessions"
    sessions.mkdir(parents=True)
    chat = sessions / "chat"
    chat.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cs, "_chat_dir", lambda: chat)
    return chat


def test_should_use_actor_loop_multi_specialist():
    subtasks = [
        {"agent": "rag", "task": "context"},
        {"agent": "gmail", "task": "search"},
        {"agent": "calendar", "task": "events"},
    ]
    with patch("tempa.orchestrator.actor_loop.actor_loop_enabled", return_value=True):
        assert should_use_actor_loop(subtasks, {"user_message": "mail and calendar"}) is True


def test_should_use_actor_loop_meet_channel():
    subtasks = [
        {"agent": "meet", "task": "join"},
        {"agent": "channel", "task": "notify"},
    ]
    with patch("tempa.orchestrator.actor_loop.actor_loop_enabled", return_value=True):
        assert should_use_actor_loop(subtasks, {"user_message": "join and message"}) is True


def test_should_use_actor_loop_single_specialist_fast_path():
    subtasks = [
        {"agent": "rag", "task": "context"},
        {"agent": "gmail", "task": "search"},
    ]
    with patch("tempa.orchestrator.actor_loop.actor_loop_enabled", return_value=True):
        assert should_use_actor_loop(subtasks, {"user_message": "check inbox"}) is False


def test_collect_pending_from_results_email():
    results = {
        "gmail": json.dumps(
            {
                "status": "pending",
                "pending_action_id": "abc-123",
                "to": "alice@example.com",
                "subject": "Hi",
                "preview": "Hello",
            }
        )
    }
    pending = collect_pending_from_results(results)
    assert len(pending) == 1
    assert pending[0]["id"] == "abc-123"
    assert pending[0]["type"] == "email_send"
    assert needs_pause(pending) is True


def test_collect_pending_from_results_pc_write():
    results = {
        "pc": json.dumps(
            {
                "status": "pending",
                "pending_action_id": "pc-1",
                "tool": "write_file",
                "path": "/tmp/x.txt",
            }
        )
    }
    pending = collect_pending_from_results(results)
    assert pending[0]["type"] == "pc_write"
    assert needs_pause(pending) is True


def test_enrich_conversation_context_sets_messages(chat_store, monkeypatch):
    from tempa.core import chat_sessions as cs

    sessions = chat_store.parent
    monkeypatch.setattr(cs, "_chat_dir", lambda: chat_store)

    session = cs.create_session()
    cs.append_message(session["id"], "user", "First question")
    cs.append_message(session["id"], "assistant", "First answer")

    ctx = enrich_conversation_context({"session_id": session["id"]})
    messages = ctx.get("conversation_messages") or []
    assert len(messages) >= 2
    assert messages[-2]["role"] == "user"
    assert messages[-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_run_actor_loop_executes_sequentially():
    calls: list[str] = []

    async def fake_runner(agent, task, ctx, user_message, task_id, step_id=""):
        calls.append(agent)
        if agent == "gmail":
            return json.dumps({"status": "ok", "count": 2})
        if agent == "calendar":
            return json.dumps({"status": "ok", "events": 1})
        return json.dumps({"status": "ok"})

    subtasks = [
        {"agent": "rag", "task": "context"},
        {"agent": "gmail", "task": "search mail"},
        {"agent": "calendar", "task": "list events"},
    ]
    with patch("tempa.orchestrator.actor_loop._run_specialist_with_retry", side_effect=fake_runner):
        results, ctx, paused, pending, clarification = await run_actor_loop(
            "mail and calendar",
            subtasks,
            {"user_message": "mail and calendar"},
            existing_results={"rag": json.dumps({"status": "ok"})},
        )

    assert calls == ["gmail", "calendar"]
    assert "gmail" in results
    assert "calendar" in results
    assert paused is False
    assert clarification is None
    assert len(ctx.get("action_facts") or []) >= 2


@pytest.mark.asyncio
async def test_run_actor_loop_pauses_on_email_pending():
    async def fake_runner(agent, task, ctx, user_message, task_id, step_id=""):
        if agent == "gmail":
            return json.dumps(
                {
                    "status": "pending",
                    "pending_action_id": "email-99",
                    "to": "bob@example.com",
                    "subject": "Re: meet",
                    "preview": "Sure",
                }
            )
        return json.dumps({"status": "ok"})

    subtasks = [
        {"agent": "gmail", "task": "send"},
        {"agent": "calendar", "task": "events"},
    ]
    with patch("tempa.orchestrator.actor_loop._run_specialist_with_retry", side_effect=fake_runner):
        results, _ctx, paused, pending, clarification = await run_actor_loop(
            "send email and check calendar",
            subtasks,
            {},
        )

    assert paused is True
    assert len(pending) == 1
    assert pending[0]["type"] == "email_send"
    assert "gmail" in results
    assert "calendar" not in results
    assert clarification is None


@pytest.mark.asyncio
async def test_run_actor_loop_clarifies_on_error():
    async def fake_runner(agent, task, ctx, user_message, task_id, step_id=""):
        return json.dumps({"status": "error", "reason": "Calendar not connected"})

    with patch("tempa.orchestrator.actor_loop._run_specialist_with_retry", side_effect=fake_runner):
        with patch("tempa.orchestrator.actor_loop.actor_replan_on_error", return_value=False):
            _results, _ctx, paused, pending, clarification = await run_actor_loop(
                "show calendar",
                [{"agent": "calendar", "task": "list"}],
                {"user_message": "show calendar"},
            )

    assert paused is False
    assert not pending
    assert clarification is not None
    assert "calendar" in clarification.lower()
