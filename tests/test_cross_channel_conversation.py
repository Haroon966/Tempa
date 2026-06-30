from __future__ import annotations

import json
from pathlib import Path

import pytest

from tempa.core.cross_channel_conversation import (
    collect_cross_channel_conversation,
    enrich_conversation_context,
    format_conversation_lines,
)


@pytest.fixture
def sessions_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    yield tmp_path / "sessions"
    get_settings.cache_clear()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_collect_cross_channel_conversation_merges_channels(sessions_dir):
    _write_jsonl(
        sessions_dir / "slack" / "conversation.jsonl",
        [
            {
                "role": "user",
                "text": "slack hello",
                "timestamp": "2026-06-26T10:00:00+00:00",
                "channel_id": "C1",
            }
        ],
    )
    _write_jsonl(
        sessions_dir / "whatsapp" / "conversation.jsonl",
        [
            {
                "role": "user",
                "text": "wa ping",
                "timestamp": "2026-06-26T10:05:00+00:00",
            }
        ],
    )

    from tempa.channels.slack import conversation as slack_conv
    from tempa.channels.whatsapp import conversation as wa_conv

    slack_conv._loaded = False
    slack_conv._recent_messages.clear()
    wa_conv._loaded = False
    wa_conv._recent_messages.clear()

    turns = collect_cross_channel_conversation({})
    texts = [t["text"] for t in turns]
    channels = [t["channel"] for t in turns]
    assert "slack hello" in texts
    assert "wa ping" in texts
    assert "slack" in channels
    assert "whatsapp" in channels
    assert texts.index("slack hello") < texts.index("wa ping")


def test_enrich_conversation_context_sets_recent_user_messages(sessions_dir):
    _write_jsonl(
        sessions_dir / "whatsapp" / "conversation.jsonl",
        [{"role": "user", "text": "need update", "timestamp": "2026-06-26T12:00:00+00:00"}],
    )
    from tempa.channels.whatsapp import conversation as wa_conv

    wa_conv._loaded = False

    ctx = enrich_conversation_context({"channel": "dashboard"})
    assert ctx.get("cross_channel_loaded") is True
    assert any("need update" in m for m in ctx.get("recent_user_messages") or [])


def test_format_conversation_lines_includes_channel_labels():
    lines = format_conversation_lines(
        [
            {"role": "user", "text": "hi", "channel": "slack"},
            {"role": "assistant", "text": "hey", "channel": "dashboard"},
        ]
    )
    assert lines == ["[slack] user: hi", "[dashboard] assistant: hey"]


def test_slack_turns_scoped_to_inbound_channel(sessions_dir):
    _write_jsonl(
        sessions_dir / "slack" / "conversation.jsonl",
        [
            {
                "role": "user",
                "text": "in C1",
                "timestamp": "2026-06-26T10:00:00+00:00",
                "channel_id": "C1",
                "conversation_key": "C1",
            },
            {
                "role": "user",
                "text": "in C2",
                "timestamp": "2026-06-26T10:01:00+00:00",
                "channel_id": "C2",
                "conversation_key": "C2",
            },
        ],
    )
    from tempa.channels.slack import conversation as slack_conv

    slack_conv._loaded = False
    slack_conv._recent_messages.clear()

    turns = collect_cross_channel_conversation(
        {
            "inbound_slack": True,
            "slack_channel_id": "C1",
            "slack_conversation_key": "C1",
        }
    )
    texts = [t["text"] for t in turns if t.get("channel") == "slack"]
    assert texts == ["in C1"]
