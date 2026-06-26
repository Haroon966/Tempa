from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_coordinator_go_approves_pending_action():
    pending = {
        "id": "act-123",
        "type": "plan_preview",
        "title": "Review coordinator plan",
        "source_channel": "dashboard",
        "status": "pending",
        "created_at": "2026-06-26T12:00:00+00:00",
    }

    with patch("tempa.core.pending_actions.list_pending_actions", return_value=[pending]):
        with patch(
            "tempa.core.pending_actions.execute_pending_action",
            new=AsyncMock(return_value={"status": "executed", "result": {"response": "Plan executed."}}),
        ) as execute:
            from tempa.agents.graph import run_coordinator_full

            result = await run_coordinator_full("go", {"channel": "dashboard"})

    execute.assert_awaited_once_with("act-123")
    assert result["response"] == "Plan executed."


@pytest.mark.asyncio
async def test_coordinator_go_rejects_non_owner_on_slack():
    with patch("tempa.core.pending_actions.list_pending_actions", return_value=[]):
        from tempa.agents.graph import run_coordinator_full

        result = await run_coordinator_full(
            "go",
            {"channel": "slack", "slack_user_id": "U999"},
        )

    assert "Only the owner" in result["response"]


@pytest.mark.asyncio
async def test_coordinator_go_emits_harness_event_when_no_pending():
    with patch("tempa.core.pending_actions.list_pending_actions", return_value=[]):
        with patch("tempa.agents.graph._emit_harness_go_signal", new=AsyncMock()) as emit:
            emit.return_value = {
                "response": "Approved — I'll proceed with the plan on the next orchestrator tick.",
                "sources": [],
                "paused": False,
                "pending_actions": [],
                "artifacts": [],
            }
            from tempa.agents.graph import run_coordinator_full

            result = await run_coordinator_full("go", {"channel": "dashboard"})

    emit.assert_awaited_once()
    assert "Approved" in result["response"]
