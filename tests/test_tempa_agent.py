"""Self-check for Tempa interactive agent (permanent Cursor front-door)."""

from __future__ import annotations

from tempa.agent.activity import merge_steps, step_from_sdk_message
from tempa.agent.context import format_memory_block
from tempa.agent.prompts import system_preamble
from tempa.agent.runner import agent_home_cwd, is_cancel_request
from tempa.agent.sessions import clear_session, get_session, save_session
from tempa.channels.slack.cursor_progress import msg_activity, msg_working


def test_brand_copy_has_no_cursor_or_groq():
    body = msg_working() + msg_activity(steps=["Reading App.tsx…"], done=False)
    lower = body.lower()
    assert "cursor" not in lower
    assert "groq" not in lower
    assert "tempa" in lower


def test_system_preamble_brand():
    text = system_preamble().lower()
    assert "tempa" in text
    assert "never mention cursor" in text or "never mention" in text


def test_cancel_detection():
    assert is_cancel_request("stop")
    assert is_cancel_request("Cancel please")
    assert not is_cancel_request("please stop the meeting from vanishing")


def test_activity_merge_and_scrub():
    class Msg:
        type = "tool_use"
        name = "meet_join"

    step = step_from_sdk_message(Msg())
    assert step and "meet" in step.lower()
    steps = merge_steps([], step)
    steps = merge_steps(steps, step)  # dedupe
    assert len(steps) == 1


def test_sessions_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    save_session(channel="C1", thread_id="1.0", agent_id="agent-abc", local_cwd="/tmp", user_id="U1")
    row = get_session(channel="C1", thread_id="1.0")
    assert row is not None
    assert row["agent_id"] == "agent-abc"
    clear_session(channel="C1", thread_id="1.0")
    assert get_session(channel="C1", thread_id="1.0") is None
    get_settings.cache_clear()


def test_agent_home_default():
    cwd = agent_home_cwd()
    assert cwd
    assert "tempa" in cwd.lower() or cwd.startswith("/")


def test_memory_block_empty_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    block = format_memory_block(user_id="U1")
    assert "durable memory" in block.lower() or "no durable" in block.lower()
    get_settings.cache_clear()


def test_custom_tools_build():
    from tempa.agent.tools import build_custom_tools

    tools = build_custom_tools(default_user_id="U1")
    assert "meet_join" in tools
    assert "memory_add_preference" in tools
    assert "calendar_create_event" in tools


def test_resolve_workspace_skips_sole_default_for_chat():
    from tempa.agent.runner import agent_home_cwd, resolve_workspace

    cwd, repo = resolve_workspace(text="what's on my calendar?", channel_id="C1", thread_ts="1.0")
    assert cwd == agent_home_cwd()
    assert repo == ""


def test_activity_ts_nested_result():
    from tempa.agent.slack_activity import _extract_message_ts

    assert _extract_message_ts({"result": {"ts": "9.9", "ok": True}}) == "9.9"


def test_bot_participated_sees_agent_session(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    from tempa.agent.sessions import save_session
    from tempa.channels.slack.conversation import bot_participated_in_thread

    save_session(channel="C99", thread_id="55.0", agent_id="pending", user_id="U1")
    assert bot_participated_in_thread("C99", "55.0") is True
    get_settings.cache_clear()
