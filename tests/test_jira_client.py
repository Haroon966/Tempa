from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest

from tempa.channels.jira.client import (
    assign_issue,
    build_updated_jql,
    create_issue,
    jira_configured,
    search_issues,
    search_users,
    since_iso_to_jql_datetime,
    test_connection as verify_jira_connection,
)
from tempa.channels.jira.session import save_jira_session_config


@pytest.fixture
def jira_env(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JIRA_BASE_URL", "https://acme.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "dev@acme.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret-token")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    save_jira_session_config(
        base_url="https://acme.atlassian.net",
        email="dev@acme.com",
        default_project="ENG",
        api_token="secret-token",
    )
    yield
    get_settings.cache_clear()


def test_jira_configured(jira_env):
    assert jira_configured() is True


def test_auth_header_uses_basic_encoding(jira_env):
    from tempa.channels.jira.client import _auth_header

    header = _auth_header()
    token = header.split(" ", 1)[1]
    decoded = base64.b64decode(token).decode("utf-8")
    assert decoded == "dev@acme.com:secret-token"


def test_since_iso_to_jql_datetime():
    assert since_iso_to_jql_datetime("2026-06-26T10:30:00Z") == "2026-06-26 10:30"


def test_build_updated_jql():
    jql = build_updated_jql(["ENG", "OPS"], "2026-06-26T10:00:00Z")
    assert 'project in (ENG, OPS)' in jql
    assert 'updated >= "2026-06-26 10:00"' in jql


def test_test_connection(jira_env):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"accountId":"abc","displayName":"Dev User","emailAddress":"dev@acme.com"}'
    mock_response.json.return_value = {
        "accountId": "abc",
        "displayName": "Dev User",
        "emailAddress": "dev@acme.com",
    }

    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.request.return_value = mock_response
        result = verify_jira_connection()

    assert result["status"] == "ok"
    assert result["display_name"] == "Dev User"


def test_search_issues(jira_env):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"{}"
    mock_response.json.return_value = {
        "issues": [
            {
                "key": "ENG-1",
                "fields": {
                    "summary": "Fix login",
                    "status": {"name": "Open"},
                    "assignee": {"displayName": "Dev"},
                    "project": {"key": "ENG"},
                    "updated": "2026-06-26T12:00:00.000+0000",
                },
            }
        ]
    }

    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.request.return_value = mock_response
        issues = search_issues("project = ENG")
        call_path = instance.request.call_args[0][1]
        assert call_path.endswith("/rest/api/3/search/jql")

    assert len(issues) == 1
    assert issues[0]["key"] == "ENG-1"
    assert issues[0]["summary"] == "Fix login"
    assert issues[0]["url"] == "https://acme.atlassian.net/browse/ENG-1"


def test_create_issue(jira_env):
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.content = b'{"id":"10001","key":"ENG-99"}'
    mock_response.json.return_value = {"id": "10001", "key": "ENG-99"}

    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.request.return_value = mock_response
        result = create_issue(project="ENG", summary="New task", description="Details")

    assert result["status"] == "ok"
    assert result["key"] == "ENG-99"


def test_search_users(jira_env):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"[]"
    mock_response.json.return_value = [
        {"accountId": "abc", "displayName": "Haroon", "emailAddress": "h@co.com", "active": True}
    ]

    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.request.return_value = mock_response
        users = search_users("Haroon")

    assert len(users) == 1
    assert users[0]["account_id"] == "abc"


def test_create_issue_with_assignee(jira_env):
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.content = b'{"id":"10001","key":"ENG-99"}'
    mock_response.json.return_value = {"id": "10001", "key": "ENG-99"}

    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.request.return_value = mock_response
        result = create_issue(
            project="ENG",
            summary="New task",
            description="Details",
            assignee_account_id="abc123",
            priority="High",
        )
        body = instance.request.call_args.kwargs.get("json") or instance.request.call_args[1].get("json")
        fields = body["fields"]
        assert fields["assignee"] == {"id": "abc123"}
        assert fields["priority"] == {"name": "High"}

    assert result["status"] == "ok"
    assert result["key"] == "ENG-99"


def test_assign_issue(jira_env):
    mock_response = MagicMock()
    mock_response.status_code = 204
    mock_response.content = b""

    with patch("httpx.Client") as mock_client:
        instance = mock_client.return_value.__enter__.return_value
        instance.request.return_value = mock_response
        result = assign_issue("ENG-1", "abc123")

    assert result["status"] == "ok"
    assert result["issue_key"] == "ENG-1"
