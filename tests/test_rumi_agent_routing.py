from __future__ import annotations

from unittest.mock import patch

import pytest

from tempa.channels.slack.cursor_progress import msg_rumi_working
from tempa.channels.slack.cursor_threads import rumi_agent_job_cfg
from tempa.channels.slack.cursor_worker import _build_agent_prompt, enqueue_from_slack
from tempa.channels.slack.rumi_pack import format_rumi_capability_reply, format_rumi_user_reply, load_rumi_pack_context, skill_inventory
from tempa.orchestrator.routing import is_coding_work_request, is_rumi_agent_request, is_rumi_capability_ask
from tempa.rumi.classify import classify_rumi


def test_classify_capability_do_you_have_rumi_skills():
    assert classify_rumi("do you have rumi skills etc") == "capability"
    assert classify_rumi("@Tempa do you have rumi skills etc") == "capability"


def test_classify_agent_use_rumi():
    assert classify_rumi("use rumi to list my Notion cards") == "agent"
    assert classify_rumi("ask rumi for teacher usage last week") == "agent"
    assert classify_rumi("rumi: list my team cards") == "agent"


def test_classify_excludes_meet_chatter_and_urls():
    assert classify_rumi("Rumi left the Meet") is None
    assert classify_rumi("rumi joined the call") is None
    assert classify_rumi("use rumi to join https://meet.google.com/abc-defg-hij") is None


def test_wrappers_match_classify():
    msg = "do you have rumi skills etc"
    assert is_rumi_agent_request(msg, {}) is True
    assert is_rumi_capability_ask(msg, {}) is True
    assert is_coding_work_request(msg, {}) is False
    assert is_rumi_capability_ask("use rumi to list cards", {}) is False


def test_github_scan_still_coding_not_rumi():
    assert classify_rumi("scan https://github.com/org/repo") is None
    assert is_coding_work_request("scan https://github.com/org/repo", {}) is True


def test_rumi_agent_job_cfg_shape():
    cfg = rumi_agent_job_cfg()
    assert cfg["job_kind"] == "rumi_agent"
    assert cfg["local_cwd"] == "/repos/rumixtempa"
    assert not cfg.get("repo")


def test_enqueue_rumi_never_write_even_on_create(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CURSOR_API_KEY", "cursor_test_key")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    pack = tmp_path / "rumixtempa"
    pack.mkdir()
    with patch("tempa.qa.cursor.cursor_configured", return_value=True):
        result = enqueue_from_slack(
            text="use rumi to create a Notion card for term-2 LPs",
            context={
                "slack_channel_id": "C1",
                "slack_thread_ts": "1.1",
                "slack_user_id": "U1",
            },
            cfg={
                "local_cwd": str(pack),
                "job_kind": "rumi_agent",
                "base_ref": "main",
                "required_checks": [],
            },
        )
    get_settings.cache_clear()
    assert "error" not in result
    from tempa.channels.slack import cursor_jobs as jobs

    row = jobs.get_job(result["job_id"])
    assert row is not None
    assert row["mode"] == "read"
    assert row.get("job_kind") == "rumi_agent"


def test_rumi_prompt_includes_full_pack_context(tmp_path):
    root = tmp_path / "rumixtempa"
    (root / "skills" / "notion-board").mkdir(parents=True)
    (root / "CLAUDE.md").write_text("# Router\n", encoding="utf-8")
    (root / "skills" / "notion-board" / "SKILL.md").write_text(
        "---\nname: notion-board\ndescription: Team Notion board cards\n---\n\n# Board\n",
        encoding="utf-8",
    )
    (root / "TOKENS.md").write_text("# tokens\n", encoding="utf-8")
    (root / "KEYS.md").write_text("# keys\n", encoding="utf-8")

    assert "`notion-board`" in skill_inventory(root)
    assert "Router" in load_rumi_pack_context(root)
    prompt = _build_agent_prompt(
        {
            "job_kind": "rumi_agent",
            "user_id": "U1",
            "local_cwd": str(root),
            "ask_text": "use rumi to list cards",
        }
    )
    assert "FULL RUMI PACK CONTEXT" in prompt
    assert "# tokens" not in prompt


def test_format_rumi_user_reply_gives_control_footer():
    out = format_rumi_user_reply("Here are your cards.")
    assert "full control" in out.lower()


def test_format_rumi_capability_reply_lists_skills():
    out = format_rumi_capability_reply()
    assert "Rumi" in out
    assert "use rumi" in out.lower()
    assert "meeting summary" not in out.lower()


def test_msg_rumi_working_is_tempa_branded():
    msg = msg_rumi_working()
    assert "Rumi" in msg
    assert "Cursor" not in msg
    assert "background" in msg.lower()


@pytest.mark.asyncio
async def test_rumi_pack_hook_blocks_coordinator_invention():
    from tempa.orchestrator.hooks_impl import rumi_pack_hook

    result = await rumi_pack_hook("do you have rumi skills etc", {"channel": "slack"})
    assert result is not None
    assert "Rumi" in result["response"]
    assert "meeting summary" not in result["response"].lower()
    assert "Deep Dive" not in result["response"]


@pytest.mark.asyncio
async def test_rag_skips_for_rumi_pack_asks():
    from tempa.agents.specialists import run_rag_agent_task

    text, sources = await run_rag_agent_task(
        "do you have rumi skills",
        {"user_message": "do you have rumi skills", "channel": "slack"},
    )
    assert sources == []
    assert "No relevant memory" in text
