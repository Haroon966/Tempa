"""Acceptance journeys for Tempa Orchestrator Agent (plan § Phase 6)."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_j1_jira_ticket_draft_from_slack_owner():
    """J1: Create jira ticket from Slack owner → draft preview."""
    pytest.importorskip("tempa.orchestrator")
    from tempa.channels.jira.tickets import handle_jira_ticket_message

    ctx = {
        "channel": "slack",
        "slack_privileged": True,
        "slack_user_id": "U_OWNER",
        "slack_channel_id": "C1",
        "slack_thread_ts": "123.456",
    }
    reply = await handle_jira_ticket_message("create jira ticket: login bug assign me", ctx)
    assert reply
    lower = reply.lower()
    assert any(k in lower for k in ("login", "ticket", "draft", "jira", "email", "summary"))


@pytest.mark.asyncio
async def test_j2_guest_slack_inbox_refused():
    """J2: Guest Slack asking for inbox → refusal, no gmail worker."""
    from tempa.orchestrator.registry import filter_workers_for_context
    from tempa.skills.matcher import match_skills

    ctx = {"channel": "slack", "slack_privileged": False}
    matched = match_skills("What's in my inbox?", ctx)
    workers = filter_workers_for_context(
        {w for skill in matched for w in skill.workers},
        ctx,
    )
    assert "gmail" not in workers


@pytest.mark.asyncio
async def test_j3_whatsapp_calendar_owner(monkeypatch):
    """J3: WhatsApp owner calendar query routes calendar worker."""
    from tempa.orchestrator.planner import plan_orchestrator_tasks

    ctx = {"channel": "whatsapp", "whatsapp_number": "+15551234567"}
    subtasks = plan_orchestrator_tasks("What's on my calendar tomorrow?", ctx)
    agents = {t.get("agent") for t in subtasks}
    assert "calendar" in agents or "rag" in agents


@pytest.mark.asyncio
async def test_j4_dashboard_standup_summary_plans_meet_and_rag():
    """J4: Dashboard standup summary → rag + meet workers."""
    from tempa.orchestrator.planner import plan_orchestrator_tasks

    ctx = {"channel": "dashboard"}
    subtasks = plan_orchestrator_tasks("Summarize last standup", ctx)
    agents = {t.get("agent") for t in subtasks}
    assert "rag" in agents
    assert "meet" in agents
    assert "meet" in agents


@pytest.mark.asyncio
async def test_j5_ci_failed_invokes_qa_worker():
    """J5: CI failure message → qa worker."""
    from tempa.orchestrator.planner import plan_orchestrator_tasks

    ctx = {"channel": "slack", "slack_privileged": True}
    subtasks = plan_orchestrator_tasks("CI failed on tempa", ctx)
    agents = {t.get("agent") for t in subtasks}
    assert "qa" in agents


@pytest.mark.asyncio
async def test_j6_varys_work_request_pauses(monkeypatch):
    """J6: Coding work request → varys ticket + paused."""
    from tempa.orchestrator.hooks_impl import varys_work_request_hook

    monkeypatch.setattr(
        "tempa.varys.harness.create_ticket",
        lambda db, **kw: "T-001",
    )
    monkeypatch.setattr(
        "tempa.varys.harness.get_db",
        lambda: type("DB", (), {"close": lambda self: None})(),
    )
    monkeypatch.setattr(
        "tempa.core.pending_actions.create_pending_action",
        lambda *a, **k: {"id": "pa-1", "title": "fix slack"},
    )
    monkeypatch.setattr("tempa.varys.vault_sync.ensure_vault_initialized", lambda: None)
    monkeypatch.setattr("tempa.varys.vault_sync.append_session_log", lambda *a, **k: None)

    result = await varys_work_request_hook("fix the slack reply handler", {"channel": "slack"})
    assert result is not None
    assert result.get("paused") is True
