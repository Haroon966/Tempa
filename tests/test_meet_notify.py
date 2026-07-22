from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tempa.channels.gmail.compose import finalize_beautiful_email, is_beautiful_email_html
from tempa.meet.notify import (
    _youtube_video_id,
    build_meeting_summary_email,
    build_meeting_summary_html,
    format_meeting_summary,
    is_punjab_daily_sync,
    notify_meeting_completed,
)


def test_format_meeting_summary_includes_sections():
    minutes = {
        "tldr": "Shipped compression middleware.",
        "decisions": [{"summary": "Use 25KB compression on attendance API"}],
        "action_items": [{"owner": "Mavia", "task": "Deploy filter UI", "due": "Friday"}],
        "open_questions": [{"question": "What is PISP/PSRP?"}],
    }
    text = format_meeting_summary(
        "Team Punjab – Daily Sync",
        minutes,
        meet_link="https://meet.google.com/pdd-pnhn-ogp",
        for_slack=True,
    )
    assert "Team Punjab" in text
    assert "Shipped compression" in text
    assert "Decisions" in text
    assert "Action items" in text
    assert "Open questions" in text
    assert "pdd-pnhn-ogp" in text


def test_build_meeting_summary_html_is_visually_structured():
    title = "Daily Huddle-Moawin Team Simulation"
    minutes = {
        "tldr": (
            "The team discussed creating a feedback channel, reviewing a video, pending tickets, "
            "teacher feedback, blockers, and the partial rollout of the Roomi tool across regions. "
            "Decisions were made to set up the channel, watch the video, and continue using Roomi where possible. "
            "Numerous action items and open questions were captured."
        ),
        "decisions": [
            {"summary": "Create/activate a feedback channel if one does not exist."},
            {"summary": "Review the video before the next discussion."},
            {"summary": "Continue using Roomi where it is already deployed and expand later once data/versioning is ready."},
        ],
        "action_items": [
            {"owner": "Mahrah Ashraf", "task": "Set up the feedback channel and send invitations.", "due": "ASAP"},
            {"owner": "Mahrah Ashraf", "task": "Distribute the video link and collect initial comments.", "due": "Before next meeting"},
            {"owner": "Harun", "task": "Assign the two outstanding tickets and update status.", "due": "End of week"},
            {"owner": "Harun", "task": "Follow up on the pending response reported by Harun.", "due": "Within 2 business days"},
            {"owner": "Mahrah Ashraf", "task": "Clarify the purpose and required next steps for the government-created form.", "due": "Prior to next meeting"},
            {"owner": "Harun", "task": "Draft a response to the teacher's improved idea and share it with the teacher.", "due": "Within 3 days"},
        ],
        "open_questions": [
            {"question": 'What exactly is the "solid Finnet" requirement?'},
            {"question": "How will the government-created form integrate with internal processes?"},
            {"question": "Which teams are not currently using Roomi and why?"},
        ],
    }
    html_out = build_meeting_summary_html(
        title,
        minutes,
        meet_link="https://meet.google.com/yux-ggbi-vaj",
        youtube_url="https://youtu.be/sBg6Ra_soEU",
        for_preview=True,
    )
    assert is_beautiful_email_html(html_out)
    assert "Daily Huddle-Moawin Team Simulation" in html_out
    assert "Ended" in html_out
    assert "Summary" in html_out
    assert "Decisions" in html_out
    assert "feedback channel" in html_out
    assert "Mahrah Ashraf" in html_out
    assert "due ASAP" in html_out
    assert "Harun" in html_out
    assert "solid Finnet" in html_out
    assert "Open Meet link" not in html_out
    assert "meet.google.com/yux-ggbi-vaj" in html_out
    assert "Watch meeting video" in html_out
    assert "i.ytimg.com/vi/sBg6Ra_soEU/hqdefault.jpg" in html_out
    assert 'width="552"' in html_out and 'height="311"' in html_out
    assert "*Decisions*" not in html_out
    assert "*Action items*" not in html_out
    assert "MESSAGE" not in html_out
    assert _youtube_video_id("https://youtu.be/sBg6Ra_soEU") == "sBg6Ra_soEU"

    preserved = finalize_beautiful_email(
        {
            "subject": f"Meeting notes: {title}",
            "body": format_meeting_summary(title, minutes),
            "body_html": html_out,
        }
    )
    assert preserved["body_html"] == html_out
    assert 'class="email-container"' in preserved["body_html"]
    assert "Meeting video" in preserved["body_html"]
    assert ">Tempa<" in html_out
    assert "Your AI teammate for meetings, mail, and work." in html_out
    assert ">Mail<" in html_out and "/inbox/mail" in html_out
    assert ">Slack<" in html_out and "app.slack.com" in html_out
    assert ">Dashboard<" not in html_out
    assert ">Meetings<" not in html_out
    assert "Unsubscribe" not in html_out
    assert "cid:tempa-footer-bg" in html_out or "data:image/jpeg;base64," in html_out
    assert "Design and develop by" in html_out
    assert "Haroon Ali" in html_out
    assert "https://github.com/Haroon966" in html_out
    assert "All rights reserved." not in html_out

    packed = build_meeting_summary_email(
        title,
        minutes,
        meet_link="https://meet.google.com/yux-ggbi-vaj",
        youtube_url="https://youtu.be/sBg6Ra_soEU",
    )
    assert "cid:tempa-footer-bg" in packed["html"]
    assert any(cid == "tempa-footer-bg" for cid, _, _ in packed["inline_images"])
    # Video thumb may be CID (downloaded) or https fallback
    assert "cid:tempa-meeting-thumb" in packed["html"] or "i.ytimg.com" in packed["html"]
    assert 'height="311"' in packed["html"]


def test_is_punjab_daily_sync_matches_title_variants():
    assert is_punjab_daily_sync("Team Punjab – Daily Sync")
    assert is_punjab_daily_sync("team punjab - daily sync")
    assert not is_punjab_daily_sync("Optional: Sense-making Sessions")


@pytest.mark.asyncio
async def test_notify_sends_slack_and_email_to_owner_and_organizer():
    minutes = {"tldr": "Pilot feedback loops agreed."}
    record = {
        "title": "Standup",
        "meet_link": "https://meet.google.com/abc-defg-hij",
        "organizer_email": "org@example.com",
    }

    with (
        patch("tempa.settings.get_settings") as mock_settings,
        patch("tempa.meet.notify._send_slack_dm", new_callable=AsyncMock, return_value="sent") as mock_slack,
        patch("tempa.meet.notify.find_slack_user_id_by_email", return_value="UORG"),
        patch("tempa.meet.notify._send_email_summary", new_callable=AsyncMock, return_value="sent") as mock_email,
        patch("tempa.meet.notify._summary_email_recipients", return_value=["org@example.com", "owner@example.com"]),
    ):
        settings = mock_settings.return_value
        settings.meet_auto_send_summary_whatsapp = False
        settings.meet_auto_send_summary_slack = True
        settings.meet_auto_send_summary_email = True
        settings.slack_owner_user_id = "UOWNER"

        results = await notify_meeting_completed(record, minutes)

    assert results["slack"] == "sent"
    assert results["email"] == "sent"
    assert mock_slack.await_count == 2
    assert mock_email.await_count == 2
    slack_uids = {call.args[0] for call in mock_slack.await_args_list}
    assert slack_uids == {"UOWNER", "UORG"}
    for call in mock_email.await_args_list:
        assert "MEETING NOTES" in call.kwargs["html_body"]
        assert "Pilot feedback" in call.kwargs["html_body"]
        assert "*Standup*" not in call.kwargs["html_body"]


@pytest.mark.asyncio
async def test_notify_does_not_post_punjab_channel():
    with (
        patch("tempa.settings.get_settings") as mock_settings,
        patch("tempa.meet.notify._send_slack_dm", new_callable=AsyncMock, return_value="sent"),
        patch("tempa.meet.notify._send_email_summary", new_callable=AsyncMock, return_value="sent"),
        patch("tempa.meet.notify._summary_email_recipients", return_value=[]),
    ):
        settings = mock_settings.return_value
        settings.meet_auto_send_summary_whatsapp = False
        settings.meet_auto_send_summary_slack = True
        settings.meet_auto_send_summary_email = False
        settings.slack_owner_user_id = "U1"

        results = await notify_meeting_completed(
            {"title": "Team Punjab – Daily Sync", "organizer_email": ""},
            {"tldr": "Done."},
        )

    assert "slack_punjab_channel" not in results
    assert results.get("slack") == "sent"


@pytest.mark.asyncio
async def test_notify_skips_whatsapp_by_default():
    with (
        patch("tempa.settings.get_settings") as mock_settings,
        patch("tempa.channels.whatsapp.outbound.send_whatsapp_message", new_callable=AsyncMock) as mock_wa,
        patch("tempa.meet.notify._send_slack_dm", new_callable=AsyncMock, return_value="sent"),
        patch("tempa.meet.notify._summary_email_recipients", return_value=[]),
    ):
        settings = mock_settings.return_value
        settings.meet_auto_send_summary_whatsapp = False
        settings.meet_auto_send_summary_slack = False
        settings.meet_auto_send_summary_email = False
        settings.slack_owner_user_id = ""

        results = await notify_meeting_completed(
            {"title": "Weekly"},
            {"tldr": "Done."},
            notify_number="923001234567",
        )

    assert "whatsapp" not in results
    mock_wa.assert_not_awaited()
