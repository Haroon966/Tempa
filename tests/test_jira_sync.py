from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tempa.channels.jira.sync import load_sync_state, save_sync_state, sync_jira_users_blocking


@pytest.fixture
def jira_sync_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path / "data"))
    from tempa.settings import get_settings
    from tempa.channels.jira.session import save_jira_session_config

    get_settings.cache_clear()
    save_jira_session_config(
        base_url="https://acme.atlassian.net",
        email="dev@acme.com",
        default_project="ENG",
        api_token="secret",
    )
    yield
    get_settings.cache_clear()


def test_sync_jira_users_upserts_contacts(jira_sync_env):
    users = [
        {"account_id": "abc", "display_name": "Haroon", "email": "h@co.com", "active": True},
        {"account_id": "def", "display_name": "Ali", "email": "a@co.com", "active": True},
    ]

    with patch("tempa.channels.jira.sync.jira_configured", return_value=True), patch(
        "tempa.channels.jira.sync.list_assignable_users", return_value=users
    ), patch("tempa.channels.contacts.linker.link_identities", return_value={"identity_link_count": 2}), patch(
        "tempa.channels.contacts.store.upsert_contacts", new_callable=AsyncMock, return_value=2
    ):
        result = sync_jira_users_blocking()

    assert result["status"] == "ok"
    assert result["user_count"] == 2
    state = load_sync_state()
    assert state["user_count"] == 2
    assert state["last_sync_at"]


def test_sync_state_roundtrip(jira_sync_env, tmp_path):
    save_sync_state({"last_sync_at": "2026-06-26T12:00:00+00:00", "user_count": 5})
    state = load_sync_state()
    assert state["user_count"] == 5
