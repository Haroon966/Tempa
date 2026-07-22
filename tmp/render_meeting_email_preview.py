#!/usr/bin/env python3
"""Render meeting email preview with the Moawin huddle fixture."""
from pathlib import Path
from tempa.meet.notify import build_meeting_summary_html

TITLE = "Daily Huddle-Moawin Team Simulation"
MINUTES = {
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

def main() -> None:
    html = build_meeting_summary_html(
        TITLE,
        MINUTES,
        meet_link="https://meet.google.com/yux-ggbi-vaj",
        youtube_url="https://youtu.be/sBg6Ra_soEU",
        for_preview=True,
    )
    out = Path(__file__).with_name("meeting-email-preview.html")
    out.write_text(html, encoding="utf-8")
    print(out)

if __name__ == "__main__":
    main()
