"""Tests for QA agent playbook."""

from tempa.qa.agent_playbook import build_agent_playbook
from tempa.qa.store import add_finding, get_finding


def test_agent_playbook_claude():
    record = add_finding(
        repo="org/repo",
        branch="main",
        severity="high",
        category="lint",
        title="ruff error",
        body="E501 line too long",
        file="src/foo.py",
    )
    finding = get_finding(record["id"])
    assert finding
    pb = build_agent_playbook(finding, target="claude")
    assert pb["target"] == "claude"
    assert pb["finding_id"] == record["id"]
    assert "curl" in pb["prompt"]
    assert pb["terminal_command"] and "claude" in pb["terminal_command"]
    assert "post_comment" in pb["curl_commands"]


def test_agent_playbook_cursor():
    record = add_finding(
        repo="org/repo",
        branch="dev",
        severity="medium",
        category="test_failure",
        title="pytest failed",
    )
    finding = get_finding(record["id"])
    assert finding
    pb = build_agent_playbook(finding, target="cursor")
    assert pb["target"] == "cursor"
    assert pb["terminal_command"] is None
    assert "Cursor" in pb["launch_hint"]
