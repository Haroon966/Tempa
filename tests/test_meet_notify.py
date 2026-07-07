from __future__ import annotations

from tempa.meet.notify import format_meeting_summary


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
