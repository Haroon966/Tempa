from __future__ import annotations

from tempa.channels.slack.conversation import bot_participated_in_thread, record_conversation_turn
from tempa.channels.slack.messages import (
    ERROR_GENERIC,
    GREETING_CONTINUE,
    GREETING_NEW,
    greeting_for_slack,
)


def test_greeting_new_without_history():
    from tempa.channels.slack import conversation as slack_conv

    slack_conv._recent_messages.clear()
    assert greeting_for_slack({"slack_channel_id": "D1", "slack_conversation_key": "D1"}) == GREETING_NEW


def test_greeting_continue_after_bot_reply():
    from tempa.channels.slack import conversation as slack_conv

    slack_conv._recent_messages.clear()
    record_conversation_turn(
        role="assistant",
        text="On it",
        channel_id="C_TEAM",
        conversation_key="100.0",
    )
    ctx = {"slack_channel_id": "C_TEAM", "slack_conversation_key": "100.0"}
    assert greeting_for_slack(ctx) == GREETING_CONTINUE
    assert bot_participated_in_thread("C_TEAM", "100.0") is True


def test_error_constants_no_exception_leak():
    assert "exc" not in ERROR_GENERIC.lower()
    assert "traceback" not in ERROR_GENERIC.lower()
