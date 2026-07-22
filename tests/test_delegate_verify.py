from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from tempa.core.pending_actions import needs_owner_pause
from tempa.orchestrator.actor_loop import needs_pause
from tempa.orchestrator.delegate import delegate_tasks


@pytest.mark.asyncio
async def test_delegate_tasks_clarifies_on_verify_failure():
    async def fake_runner(agent, task, ctx, user_message, task_id, step_id=""):
        return json.dumps({"status": "error", "reason": "Gmail not connected"})

    with patch("tempa.agents.graph._run_specialist_with_retry", side_effect=fake_runner):
        with patch("tempa.orchestrator.actor_loop.actor_replan_on_error", return_value=False):
            results, _ctx, clarification = await delegate_tasks(
                "check inbox",
                [{"agent": "gmail", "task": "search"}],
                {"user_message": "check inbox"},
            )

    assert "gmail" in results
    assert clarification is not None
    assert "gmail" in clarification.lower()


@pytest.mark.asyncio
async def test_delegate_tasks_ok_path_no_clarify():
    async def fake_runner(agent, task, ctx, user_message, task_id, step_id=""):
        return json.dumps({"status": "ok", "count": 1})

    with patch("tempa.agents.graph._run_specialist_with_retry", side_effect=fake_runner):
        results, _ctx, clarification = await delegate_tasks(
            "check inbox",
            [{"agent": "gmail", "task": "search"}],
            {"user_message": "check inbox"},
        )

    assert clarification is None
    assert "gmail" in results


def test_needs_pause_includes_slack_send():
    pending = [{"id": "1", "type": "slack_send", "risk_level": "high"}]
    assert needs_owner_pause(pending) is True
    assert needs_pause(pending) is True


def test_needs_pause_high_risk_even_if_type_unknown_to_pause_set():
    pending = [{"id": "2", "type": "plan_preview", "risk_level": "high"}]
    assert needs_owner_pause(pending) is True
