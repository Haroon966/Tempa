from __future__ import annotations

from tempa.channels.slack.varys_bridge import classify_slack_message, enrich_slack_context
from tempa.varys.manager import is_go_signal


def test_go_signal_detection():
    assert is_go_signal("go")
    assert is_go_signal("Approve")
    assert not is_go_signal("go fix it")


def test_classify_slack_message():
    assert classify_slack_message("go", user_id="U1", owner_user_id="U1") == "go_signal"
    assert classify_slack_message("go", user_id="U2", owner_user_id="U1") == "conversational"
    assert classify_slack_message("fix login bug", user_id="U2", owner_user_id="U1") == "work_request"


def test_enrich_slack_context():
    ctx = enrich_slack_context(
        {"user": "U1", "channel": "C1", "ts": "1.0", "thread_ts": "0.9", "channel_type": "channel"},
        {"slack_privileged": True},
    )
    assert ctx["channel"] == "slack"
    assert ctx["slack_user_id"] == "U1"
    assert ctx["slack_thread_ts"] == "0.9"
