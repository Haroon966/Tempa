from __future__ import annotations

from unittest.mock import patch

import pytest

from tempa.channels.jira.profiles import get_profile, remember_jira_email, save_profile
from tempa.channels.jira.users import resolve_jira_user


@pytest.fixture
def profile_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path / "data"))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_profile_persist_and_reuse(profile_env):
    save_profile(
        slack_user_id="U123",
        jira_account_id="abc",
        jira_email="h@co.com",
        display_name="Haroon",
        default_project="ENG",
        source="slack_profile",
    )
    profile = get_profile(slack_user_id="U123")
    assert profile["jira_account_id"] == "abc"
    assert profile["default_project"] == "ENG"


def test_remember_jira_email(profile_env):
    remember_jira_email(slack_user_id="U99", email="new@co.com")
    profile = get_profile(slack_user_id="U99")
    assert profile["jira_email"] == "new@co.com"


def test_resolver_uses_profile(profile_env):
    save_profile(slack_user_id="U123", jira_account_id="abc", display_name="Haroon")
    result = resolve_jira_user("Haroon", slack_user_id="U123", self_assign=True)
    assert result.account_id == "abc"
    assert result.source == "profile"


def test_resolver_uses_link(profile_env):
    with patch("tempa.channels.jira.users.resolve_slack_to_jira") as mock_link:
        mock_link.return_value = {"account_id": "linked", "display_name": "Haroon", "email": "h@co.com"}
        result = resolve_jira_user("", slack_user_id="U123", self_assign=True)
    assert result.account_id == "linked"
    assert result.source == "link"


def test_resolver_ambiguous_live(profile_env):
    with patch("tempa.channels.jira.users.search_users") as mock_search:
        mock_search.return_value = [
            {"account_id": "1", "display_name": "Haroon A", "email": ""},
            {"account_id": "2", "display_name": "Haroon B", "email": ""},
        ]
        result = resolve_jira_user("Haroon")
    assert len(result.ambiguous) == 2
