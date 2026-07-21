from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_coordinator_uses_orchestrator_when_adk_spike_off(monkeypatch):
    from tempa.settings import get_settings

    monkeypatch.setenv("TEMPA_ADK_SPIKE", "false")
    monkeypatch.setenv("TEMPA_COORDINATOR", "langgraph")
    get_settings.cache_clear()

    fake = {"response": "legacy", "sources": [], "paused": False, "pending_actions": [], "artifacts": [], "planned_steps": []}
    with (
        patch("tempa.orchestrator.hooks.run_pre_hooks", new=AsyncMock(return_value=None)),
        patch("tempa.orchestrator.hooks_impl.register_all_hooks"),
        patch(
            "tempa.core.cross_channel_conversation.enrich_conversation_context",
            side_effect=lambda c: c,
        ),
        patch("tempa.agents.graph._should_use_varys", return_value=False),
        patch("tempa.orchestrator.agent.run_orchestrator", new=AsyncMock(return_value=fake)) as orch,
        patch("tempa.adk.run_adk_orchestrator", new=AsyncMock()) as adk,
    ):
        from tempa.agents.graph import run_coordinator_full

        result = await run_coordinator_full("hello", {"channel": "dashboard"})

    assert result["response"] == "legacy"
    orch.assert_awaited_once()
    adk.assert_not_called()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_coordinator_uses_adk_when_spike_on(monkeypatch):
    from tempa.settings import get_settings

    monkeypatch.setenv("TEMPA_ADK_SPIKE", "true")
    monkeypatch.setenv("TEMPA_COORDINATOR", "langgraph")
    get_settings.cache_clear()

    fake = {
        "response": "adk",
        "sources": [{"id": "1"}],
        "paused": False,
        "pending_actions": [],
        "artifacts": [],
        "planned_steps": [{"agent": "rag"}],
    }
    with (
        patch("tempa.orchestrator.hooks.run_pre_hooks", new=AsyncMock(return_value=None)),
        patch("tempa.orchestrator.hooks_impl.register_all_hooks"),
        patch(
            "tempa.core.cross_channel_conversation.enrich_conversation_context",
            side_effect=lambda c: c,
        ),
        patch("tempa.agents.graph._should_use_varys", return_value=False),
        patch("tempa.orchestrator.agent.run_orchestrator", new=AsyncMock()) as orch,
        patch("tempa.adk.run_adk_orchestrator", new=AsyncMock(return_value=fake)) as adk,
    ):
        from tempa.agents.graph import run_coordinator_full

        result = await run_coordinator_full("search memory", {"channel": "dashboard", "session_id": "s1"})

    assert result["response"] == "adk"
    assert result["sources"] == [{"id": "1"}]
    adk.assert_awaited_once()
    orch.assert_not_called()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_rag_tool_forwards_task_and_collects_sources():
    from tempa.adk import tools as adk_tools

    adk_tools.set_run_context({"channel": "dashboard"})

    async def fake_rag(task: str, context: dict):
        assert task == "what did we decide"
        assert context["channel"] == "dashboard"
        return "decided X", [{"source": "mem"}]

    with patch("tempa.agents.specialists.run_rag_agent_task", new=fake_rag):
        out = await adk_tools.rag_search("what did we decide")

    assert out == "decided X"
    assert adk_tools.get_collected_sources() == [{"source": "mem"}]


@pytest.mark.asyncio
async def test_gmail_and_calendar_tools_forward_task():
    from tempa.adk import tools as adk_tools

    adk_tools.set_run_context({"channel": "slack"})

    async def fake_gmail(task: str, context: dict):
        assert task == "unread from boss"
        assert context["channel"] == "slack"
        return "3 unread"

    async def fake_cal(task: str, context: dict):
        assert task == "tomorrow"
        return "2 events"

    with (
        patch("tempa.agents.specialists.run_gmail_agent", new=fake_gmail),
        patch("tempa.agents.specialists.run_calendar_agent", new=fake_cal),
    ):
        assert await adk_tools.gmail_task("unread from boss") == "3 unread"
        assert await adk_tools.calendar_task("tomorrow") == "2 events"
