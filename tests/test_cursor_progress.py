"""Tempa Cursor Slack progress copy."""

from tempa.channels.slack.cursor_progress import msg_problem
from tempa.core.chat_errors import sanitize_user_error


def test_msg_problem_dubious_ownership_is_actionable():
    msg = msg_problem(
        "fatal: detected dubious ownership in repository at '/repos/compliancetracker'\n"
        "To add an exception for this directory, call:\n\n"
        "\tgit config --global --add safe.directory /repos/compliancetracker"
    )
    assert "ask again" in msg.lower()
    assert "fatal:" not in msg.lower()
    assert "git config" not in msg.lower()
    assert "dubious" not in msg.lower()


def test_msg_problem_timeout_suggests_retry():
    msg = msg_problem("TimeoutError")
    assert "too long" in msg.lower() or "retry" in msg.lower()
    assert "TimeoutError" not in msg


def test_msg_problem_never_leaks_raw_exception():
    msg = msg_problem("boom happened with /repos/compliancetracker and traceback")
    assert "boom happened" not in msg
    assert "traceback" not in msg.lower()
    assert "ask again" in msg.lower() or "something went wrong" in msg.lower()


def test_sanitize_keeps_technical_detail_out_of_slack():
    raw = "RuntimeError: gh pr create failed: HTTP 403 GraphQL: Resource not accessible"
    out = sanitize_user_error(raw)
    assert "GraphQL" not in out
    assert "403" not in out or "rate" in out.lower()
    assert len(out) < 200
