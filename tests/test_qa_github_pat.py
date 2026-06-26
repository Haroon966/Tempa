"""Tests for GitHub PAT authentication."""

import pytest

from tempa.qa.config import load_qa_config
from tempa.qa.github.auth import get_github_token, github_auth_mode, github_configured, github_uses_pat
from tempa.qa.installations import list_repos, upsert_installation


def _refresh_settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    from tempa.settings import get_settings

    get_settings.cache_clear()
    load_qa_config.cache_clear()


def test_github_configured_with_pat_only(monkeypatch: pytest.MonkeyPatch):
    _refresh_settings(monkeypatch, GITHUB_TOKEN="ghp_test_token", GITHUB_APP_ID="", GITHUB_PRIVATE_KEY="")
    assert github_configured() is True
    assert github_uses_pat() is True
    assert github_auth_mode() == "pat"


def test_github_configured_with_app_only(monkeypatch: pytest.MonkeyPatch):
    _refresh_settings(
        monkeypatch,
        GITHUB_TOKEN="",
        GITHUB_APP_ID="12345",
        GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
    )
    assert github_configured() is True
    assert github_uses_pat() is False
    assert github_auth_mode() == "app"


def test_get_github_token_returns_pat_without_installation(monkeypatch: pytest.MonkeyPatch):
    _refresh_settings(monkeypatch, GITHUB_TOKEN="ghp_test_token")
    assert get_github_token("owner/repo") == "ghp_test_token"


def test_list_repos_merges_env_and_installations(monkeypatch: pytest.MonkeyPatch):
    _refresh_settings(monkeypatch, GITHUB_REPOS="env-org/env-repo,other/repo")
    upsert_installation(1, "test-org", [{"full_name": "test-org/tempa", "id": 1}])
    repos = list_repos()
    assert "env-org/env-repo" in repos
    assert "other/repo" in repos
    assert "test-org/tempa" in repos


def test_qa_scan_auto_adds_from_dashboard(client, monkeypatch: pytest.MonkeyPatch):
    _refresh_settings(monkeypatch, GITHUB_TOKEN="ghp_test_token", GITHUB_REPOS="")
    r = client.post("/api/qa/scan", json={"repo": "new/dashboard-repo"})
    assert r.status_code == 200
    assert r.json()["status"] == "queued"
    listed = client.get("/api/qa/repos").json()
    names = [row["repo"] for row in listed["repos"]]
    assert "new/dashboard-repo" in names


def test_qa_scan_queues_listed_repo_with_pat(client, monkeypatch: pytest.MonkeyPatch):
    _refresh_settings(monkeypatch, GITHUB_TOKEN="ghp_test_token", GITHUB_REPOS="allowed/repo")
    r = client.post("/api/qa/scan", json={"repo": "allowed/repo"})
    assert r.status_code == 200
    assert r.json()["status"] == "queued"


def test_qa_summary_includes_auth_mode(client, monkeypatch: pytest.MonkeyPatch):
    _refresh_settings(monkeypatch, GITHUB_TOKEN="ghp_test_token")
    r = client.get("/api/qa/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["github_configured"] is True
    assert data["github_auth_mode"] == "pat"
