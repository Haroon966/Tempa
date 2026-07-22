"""Cursor sessions dashboard API + Slack thread history."""

from __future__ import annotations

import json
from pathlib import Path

from tempa.channels.slack.conversation import list_thread_messages


def test_list_thread_messages_reads_jsonl(tmp_path: Path, monkeypatch):
    sessions = tmp_path / "sessions" / "slack"
    sessions.mkdir(parents=True)
    path = sessions / "conversation.jsonl"
    rows = [
        {
            "role": "user",
            "user_id": "U1",
            "channel_id": "C1",
            "text": "https://github.com/a/b improve",
            "thread_ts": "1.1",
            "conversation_key": "1.1",
            "timestamp": "2026-07-22T10:00:00+00:00",
        },
        {
            "role": "assistant",
            "user_id": "U1",
            "channel_id": "C1",
            "text": "On it",
            "thread_ts": "1.1",
            "conversation_key": "1.1",
            "timestamp": "2026-07-22T10:00:01+00:00",
        },
        {
            "role": "user",
            "user_id": "U1",
            "channel_id": "C1",
            "text": "other thread",
            "thread_ts": "2.2",
            "conversation_key": "2.2",
            "timestamp": "2026-07-22T10:00:02+00:00",
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        "tempa.channels.slack.conversation.get_settings",
        lambda: type("S", (), {"sessions_dir": tmp_path / "sessions"})(),
    )

    from tempa.channels.slack.conversation import bot_participated_in_thread, list_thread_messages

    turns = list_thread_messages(channel_id="C1", thread_ts="1.1")
    assert len(turns) == 2
    assert turns[0]["text"].startswith("https://github.com")
    assert turns[1]["role"] == "assistant"
    assert bot_participated_in_thread("C1", "1.1") is True
    assert bot_participated_in_thread("C1", "2.2") is False
