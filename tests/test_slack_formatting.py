from __future__ import annotations

import pytest

from tempa.channels.slack.formatting import format_for_slack, prepare_slack_reply


def test_bold_markdown_to_mrkdwn():
    assert format_for_slack("**Jira ticket preview**") == "*Jira ticket preview*"


def test_markdown_link_to_slack():
    result = format_for_slack("[ENG-1](https://acme.atlassian.net/browse/ENG-1)")
    assert result == "<https://acme.atlassian.net/browse/ENG-1|ENG-1>"


def test_preserves_slack_mention():
    text = "Hey <@U123> check **this**"
    assert "<@U123>" in format_for_slack(text)
    assert "*this*" in format_for_slack(text)


def test_preserves_slack_link():
    text = "See <https://example.com|docs> and **bold**"
    assert "<https://example.com|docs>" in format_for_slack(text)


def test_code_fence_strips_lang():
    raw = "```python\nprint('hi')\n```"
    assert format_for_slack(raw) == "```\nprint('hi')\n```"


def test_idempotent_mrkdwn_bold():
    text = "*already bold*"
    assert format_for_slack(text) == text


def test_prepare_slack_reply_strips():
    assert prepare_slack_reply("  **hi**  ") == "*hi*"
