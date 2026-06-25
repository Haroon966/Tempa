from __future__ import annotations

from unittest.mock import patch

from tempa.agents.grounding import build_grounding_pack, format_grounding_for_prompt
from tempa.channels.gmail.context import build_gmail_context_pack, format_gmail_context_for_prompt


def test_gmail_compact_shows_unread():
    snapshot = {
        "last_sync_at": "2026-06-21T12:00:00+00:00",
        "unread_count": 2,
        "inbox": [
            {
                "from": "alice@example.com",
                "subject": "Budget review",
                "date": "Mon, 21 Jun 2026",
                "snippet": "Please review",
                "unread": True,
            },
            {
                "from": "bob@example.com",
                "subject": "Thanks",
                "date": "Sun, 20 Jun 2026",
                "snippet": "Got it",
                "unread": False,
            },
        ],
        "recent_sent": [],
    }
    with patch("tempa.channels.gmail.context.load_gmail_snapshot", return_value=snapshot):
        with patch("tempa.channels.gmail.oauth.load_gmail_client", return_value=object()):
            pack = build_gmail_context_pack()
            text = format_gmail_context_for_prompt(pack, compact=True)

    assert "2 unread" in text
    assert "Budget review" in text


def test_grounding_includes_gmail_and_whatsapp_blocks():
    with patch("tempa.channels.whatsapp.context.build_whatsapp_context_pack") as wa:
        wa.return_value = {
            "formatted_thread": "You: hello\nTempa: hi",
            "thread_summary": "2 turns",
            "recent_user_only": ["hello"],
            "recent_thread": [],
        }
        with patch("tempa.channels.gmail.context.build_gmail_context_pack") as gm:
            gm.return_value = {
                "connection_status": "Gmail: connected",
                "unread_count": 1,
                "inbox_compact": [],
                "inbox_recent": [],
                "recent_sent": [],
                "pending_drafts": [],
                "calendar_links": [],
                "snippet_limit": 200,
            }
            with patch("tempa.channels.gmail.context.format_gmail_context_for_prompt", return_value="Inbox: 1 unread"):
                with patch("tempa.channels.calendar.context.build_meeting_context_pack") as cal:
                    cal.return_value = {
                        "today_summary": "Today (0 events)",
                        "upcoming": [],
                        "recent_past": [],
                        "recently_canceled": [],
                        "live_meeting": "",
                    }
                    with patch(
                        "tempa.channels.calendar.context.format_meeting_context_for_prompt",
                        return_value="Calendar today:\nToday (0 events)",
                    ):
                        with patch("tempa.meet.archive.get_recent_meetings_context", return_value="Recent meeting archives:"):
                            pack = build_grounding_pack("hello", {"channel": "whatsapp"})

    prompt = format_grounding_for_prompt(pack)
    assert "You: hello" in prompt
    assert "Inbox: 1 unread" in prompt
    assert "Calendar today" in prompt
