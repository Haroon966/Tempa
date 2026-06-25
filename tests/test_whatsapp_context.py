from __future__ import annotations

from unittest.mock import patch

from tempa.channels.whatsapp.context import build_whatsapp_context_pack, format_whatsapp_thread_for_prompt


def test_whatsapp_thread_includes_assistant_replies():
    thread = [
        {"role": "user", "text": "Schedule a meeting", "timestamp": "2026-06-21T10:00:00+00:00"},
        {"role": "assistant", "text": "Done — Product Sync at 3pm.", "timestamp": "2026-06-21T10:00:05+00:00"},
        {"role": "user", "text": "What time?", "timestamp": "2026-06-21T10:01:00+00:00"},
    ]
    with patch("tempa.channels.whatsapp.context.get_conversation_thread", return_value=thread):
        pack = build_whatsapp_context_pack("What time?", limit=20)

    assert len(pack["recent_thread"]) == 3
    assert "Tempa:" in pack["formatted_thread"]
    assert "You:" in pack["formatted_thread"]
    prompt = format_whatsapp_thread_for_prompt(pack)
    assert "Product Sync" in prompt


def test_follow_up_bumps_thread_limit():
    with patch("tempa.channels.whatsapp.context.get_conversation_thread") as get_thread:
        get_thread.return_value = []
        build_whatsapp_context_pack("what about that email?", limit=20)
        get_thread.assert_called_once_with(30, include_assistant=True)
