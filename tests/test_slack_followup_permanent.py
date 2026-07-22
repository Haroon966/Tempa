"""Permanent guards for Slack mid-thread + GitHub→Cursor routing."""

from __future__ import annotations

import inspect

import tempa.channels.slack.conversation as conv
from tempa.channels.slack.context import should_handle_channel_thread
from tempa.channels.slack.cursor_threads import match_cursor_repo


def test_bot_participated_export_is_a_real_function():
    """Regression: Sessions API edit once deleted this symbol and killed follow-ups."""
    assert callable(conv.bot_participated_in_thread)
    assert "channel_id" in inspect.signature(conv.bot_participated_in_thread).parameters


def test_completed_cursor_thread_still_handles_followup_without_mention(monkeypatch):
    monkeypatch.setattr(
        "tempa.channels.slack.cursor_threads.is_cursor_thread",
        lambda *a, **k: False,
    )
    monkeypatch.setattr(
        "tempa.channels.slack.conversation.bot_participated_in_thread",
        lambda channel_id, thread_ts: True,
    )
    event = {
        "channel": "C_TEAM",
        "channel_type": "channel",
        "thread_ts": "100.1",
        "ts": "100.9",
        "text": "rase pr and fix it all",
        "user": "U_DEV",
    }
    assert should_handle_channel_thread(event, event["text"]) is True


def test_explicit_github_url_beats_ct_alias_even_with_project_word(monkeypatch, tmp_path):
    import yaml
    import tempa.channels.slack.cursor_threads as ct

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "cursor_threads.yaml").write_text(
        yaml.safe_dump(
            {
                "repos": [
                    {
                        "id": "compliancetracker",
                        "local_cwd": "/repos/compliancetracker",
                        "repo": "Orenda-Project/compliancetracker",
                        "aliases": ["ct", "compliancetracker", "compliance tracker"],
                    }
                ],
                "threads": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ct, "get_settings", lambda: type("S", (), {"config_dir": cfg_dir})())
    ct._cache_mtime = None
    ct._cache_threads = []
    ct._cache_repos = []

    cfg = match_cursor_repo(
        "https://github.com/Haroon966/Klip-Board   how can we improve this project",
        allow_sole_default=False,
    )
    assert cfg is not None
    assert cfg["repo"] == "Haroon966/Klip-Board"
    assert cfg["local_cwd"] == ""
