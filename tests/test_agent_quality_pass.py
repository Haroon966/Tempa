from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from tempa.agents.graph import collect_pending_from_results, compute_execution_waves
from tempa.orchestrator.actor_loop import needs_pause, run_actor_loop, should_use_actor_loop
from tempa.orchestrator.step_verify import observe_step, verify_step


def test_should_use_actor_loop_depends_on():
    subtasks = [
        {"agent": "calendar", "task": "find meet", "depends_on": []},
        {"agent": "meet", "task": "join", "depends_on": ["calendar"]},
    ]
    with patch("tempa.orchestrator.actor_loop.actor_loop_enabled", return_value=True):
        assert should_use_actor_loop(subtasks, {"user_message": "join my meeting"}) is True


def test_compute_execution_waves_order():
    subtasks = [
        {"agent": "calendar", "task": "find", "depends_on": []},
        {"agent": "meet", "task": "join", "depends_on": ["calendar"]},
    ]
    waves = compute_execution_waves(subtasks)
    flat = [t["agent"] for wave in waves for t in wave]
    assert flat.index("calendar") < flat.index("meet")


def test_verify_step_plain_text_error():
    ok, reason = verify_step("gmail", "Gmail not connected.", None)
    assert ok is False
    assert reason


def test_observe_step_accumulates_facts():
    ctx: dict = {"action_facts": [], "step_results": []}
    observe_step(ctx, "gmail", json.dumps({"status": "ok", "count": 2}), subtask_id="g1")
    assert ctx["action_facts"]
    assert len(ctx["step_results"]) == 1


@pytest.mark.asyncio
async def test_run_actor_loop_respects_wave_order():
    order: list[str] = []

    async def fake_runner(agent, task, ctx, user_message, task_id, step_id=""):
        order.append(agent)
        return json.dumps({"status": "ok"})

    subtasks = [
        {"agent": "calendar", "task": "find", "depends_on": []},
        {"agent": "meet", "task": "join", "depends_on": ["calendar"]},
    ]
    with patch("tempa.orchestrator.actor_loop._run_specialist_with_retry", side_effect=fake_runner):
        await run_actor_loop(
            "join meeting",
            subtasks,
            {},
            existing_results={"rag": json.dumps({"status": "ok"})},
        )
    assert order == ["calendar", "meet"]


def test_collect_pending_email_pause():
    pending = collect_pending_from_results(
        {
            "gmail": json.dumps(
                {
                    "status": "pending",
                    "pending_action_id": "e1",
                    "to": "a@b.com",
                    "subject": "Hi",
                }
            )
        }
    )
    assert needs_pause(pending)
