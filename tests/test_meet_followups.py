"""Tests for post-meeting follow-up draft generation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tempa.meet.followups import create_followup_pending_actions, generate_followup_drafts
from tempa.meet.models import FollowUpDraft


@pytest.mark.asyncio
async def test_generate_followup_drafts_fallback_recap():
    minutes = {
        "tldr": "We agreed to ship Friday.",
        "action_items": [{"owner": "Bob", "task": "Deploy API", "due": "Friday"}],
    }
    with patch("tempa.meet.followups.get_router") as mock_router:
        mock_router.return_value.chat_completion.side_effect = RuntimeError("no llm")
        drafts = await generate_followup_drafts(
            minutes,
            title="Standup",
            attendee_emails=["alice@example.com", "bob@example.com"],
            transcript_excerpt="Alice: Let's ship Friday.",
        )
    assert len(drafts) >= 1
    assert drafts[0]["channel"] == "email"
    assert drafts[0]["recipient"] == "alice@example.com"


@pytest.mark.asyncio
async def test_generate_followup_drafts_from_llm_json():
    minutes = {"tldr": "Sync complete", "action_items": []}
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content='[{"channel":"whatsapp","recipient":"923001234567","body":"Thanks all","rationale":"DM"}]'
            )
        )
    ]
    with patch("tempa.meet.followups.get_router") as mock_router:
        mock_router.return_value.chat_completion.return_value = mock_response
        drafts = await generate_followup_drafts(
            minutes,
            title="Sync",
            attendee_emails=[],
            transcript_excerpt="Done.",
        )
    assert len(drafts) == 1
    assert drafts[0]["channel"] == "whatsapp"


def test_create_followup_pending_actions(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tempa.core.pending_actions._store_path",
        lambda: tmp_path / "pending.json",
    )
    drafts = [
        FollowUpDraft(
            channel="email",
            recipient="a@b.com",
            subject="Recap",
            body="Hello",
            rationale="test",
        ).model_dump()
    ]
    ids = create_followup_pending_actions("meet-1", drafts, title="Test")
    assert len(ids) == 1
