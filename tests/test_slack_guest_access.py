from __future__ import annotations

from tempa.agents.grounding import build_grounding_pack
from tempa.agents.intent import wants_private_integrations
from tempa.agents.specialists import _heuristic_subtasks, plan_subtasks
from tempa.agents.tool_policy import (
    allowed_agents,
    allowed_rag_tools,
    filter_rag_results,
    filter_subtasks,
    include_private_grounding,
    is_slack_guest,
)
from tempa.channels.slack.users import GUEST_PRIVATE_COMING_SOON, is_privileged_slack_user


def test_is_privileged_slack_user(monkeypatch):
    monkeypatch.setenv("SLACK_OWNER_USER_ID", "U_OWNER")
    monkeypatch.setenv("SLACK_ALLOWED_USER_IDS", "U_FRIEND")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    assert is_privileged_slack_user("U_OWNER") is True
    assert is_privileged_slack_user("U_FRIEND") is True
    assert is_privileged_slack_user("U_GUEST") is False
    get_settings.cache_clear()


def test_tool_policy_guest_vs_owner():
    guest_ctx = {"channel": "slack", "slack_privileged": False}
    owner_ctx = {"channel": "slack", "slack_privileged": True}

    assert is_slack_guest(guest_ctx) is True
    assert is_slack_guest(owner_ctx) is False
    assert include_private_grounding(guest_ctx) is False
    assert include_private_grounding(owner_ctx) is True
    assert allowed_agents(guest_ctx) == frozenset({"rag", "channel"})
    assert allowed_agents(owner_ctx) is None
    assert allowed_rag_tools(guest_ctx) == frozenset({"slack"})
    assert allowed_rag_tools(owner_ctx) is None


def test_filter_subtasks_for_guest():
    guest_ctx = {"channel": "slack", "slack_privileged": False}
    subtasks = [
        {"agent": "rag", "task": "x"},
        {"agent": "gmail", "task": "email"},
        {"agent": "calendar", "task": "cal"},
        {"agent": "channel", "task": "slack"},
    ]
    filtered = filter_subtasks(subtasks, guest_ctx)
    agents = {t["agent"] for t in filtered}
    assert agents == {"rag", "channel"}


def test_filter_rag_results_for_guest():
    guest_ctx = {"channel": "slack", "slack_privileged": False}
    rows = [
        {"metadata": {"tool": "gmail"}, "content": "secret"},
        {"metadata": {"tool": "slack"}, "content": "public"},
    ]
    filtered = filter_rag_results(rows, guest_ctx)
    assert len(filtered) == 1
    assert filtered[0]["metadata"]["tool"] == "slack"


def test_heuristic_subtasks_guest_skips_private_agents():
    guest_ctx = {"channel": "slack", "slack_privileged": False}
    tasks = _heuristic_subtasks("check my inbox and calendar", guest_ctx)
    agents = {t["agent"] for t in tasks}
    assert "gmail" not in agents
    assert "calendar" not in agents
    assert "rag" in agents


def test_guest_grounding_excludes_private_context(monkeypatch):
    monkeypatch.setenv("SLACK_OWNER_USER_ID", "U_OWNER")
    guest_ctx = {"channel": "slack", "slack_privileged": False}
    pack = build_grounding_pack("hi", guest_ctx)
    assert pack["gmail_compact"] == ""
    assert pack["calendar_today"] == ""
    assert pack["whatsapp_thread"] == ""
    assert pack["meet_job_facts"] == ""


def test_wants_private_integrations():
    assert wants_private_integrations("summarize my inbox") is True
    assert wants_private_integrations("what's on my calendar") is True
    assert wants_private_integrations("send a whatsapp message") is True
    assert wants_private_integrations("hello there") is False


def test_coming_soon_message():
    assert "coming soon" in GUEST_PRIVATE_COMING_SOON.lower()


def test_plan_subtasks_guest_filters(monkeypatch):
    guest_ctx = {"channel": "slack", "slack_privileged": False}
    with monkeypatch.context() as m:
        m.setattr(
            "tempa.agents.specialists._needs_llm_planning",
            lambda *_args, **_kwargs: False,
        )
        tasks = plan_subtasks("read my emails and schedule a meeting", guest_ctx)
    agents = {t["agent"] for t in tasks}
    assert "gmail" not in agents
    assert "calendar" not in agents
