"""Tests for GitHub target parsing and scan routing."""

import pytest

from tempa.qa.allowed_repos import add_repo, list_dynamic_repos, remove_repo
from tempa.qa.github.parse import parse_github_target, wants_scan_all
from tempa.qa.installations import list_repos, list_repos_detail
from tempa.qa.scan_request import handle_github_scan_request, repo_is_allowed


def _refresh_settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    from tempa.qa.config import load_qa_config
    from tempa.settings import get_settings

    get_settings.cache_clear()
    load_qa_config.cache_clear()


def test_parse_github_target_from_url():
    target = parse_github_target("scan https://github.com/acme/widgets/tree/feature-login")
    assert target.repo == "acme/widgets"
    assert target.branch == "feature-login"


def test_parse_github_target_pr_url():
    target = parse_github_target("review https://github.com/acme/widgets/pull/99")
    assert target.repo == "acme/widgets"
    assert target.pr_number == 99


def test_parse_github_target_shorthand_and_branch():
    target = parse_github_target("scan acme/widgets branch develop")
    assert target.repo == "acme/widgets"
    assert target.branch == "develop"


def test_wants_scan_all():
    assert wants_scan_all("please scan all repos")
    assert not wants_scan_all("scan acme/widgets")


def test_dynamic_repo_add_and_remove(monkeypatch: pytest.MonkeyPatch):
    _refresh_settings(monkeypatch, GITHUB_TOKEN="ghp_test", GITHUB_REPOS="")
    add_repo("dyn/org-repo", source="dashboard")
    assert "dyn/org-repo" in list_dynamic_repos()
    assert "dyn/org-repo" in list_repos()
    detail = {d["repo"]: d for d in list_repos_detail()}
    assert detail["dyn/org-repo"]["removable"] is True
    assert remove_repo("dyn/org-repo") is True
    assert "dyn/org-repo" not in list_dynamic_repos()


def test_chat_scan_pending_approval_for_new_repo(monkeypatch: pytest.MonkeyPatch):
    _refresh_settings(monkeypatch, GITHUB_TOKEN="ghp_test", GITHUB_REPOS="allowed/only")
    result = handle_github_scan_request(
        "scan https://github.com/new/org-repo branch main",
        source_channel="whatsapp",
    )
    assert result["status"] == "pending_approval"
    assert result["repo"] == "new/org-repo"
    assert result["branch"] == "main"
    assert "action_id" in result


def test_chat_scan_queues_allowed_repo(monkeypatch: pytest.MonkeyPatch):
    _refresh_settings(monkeypatch, GITHUB_TOKEN="ghp_test", GITHUB_REPOS="allowed/only")
    result = handle_github_scan_request("scan allowed/only branch main", source_channel="slack")
    assert result["status"] == "queued"
    assert result["repo"] == "allowed/only"
    assert result["branch"] == "main"


def test_dashboard_scan_auto_adds_repo(monkeypatch: pytest.MonkeyPatch):
    _refresh_settings(monkeypatch, GITHUB_TOKEN="ghp_test", GITHUB_REPOS="")
    from tempa.qa.github.parse import GitHubTarget

    result = handle_github_scan_request(
        "",
        source_channel="qa_dashboard",
        target=GitHubTarget(repo="fresh/repo"),
    )
    assert result["status"] == "queued"
    assert repo_is_allowed("fresh/repo")


def test_qa_repos_api(client, monkeypatch: pytest.MonkeyPatch):
    _refresh_settings(monkeypatch, GITHUB_TOKEN="ghp_test")
    r = client.post("/api/qa/repos", json={"repo": "api/org"})
    assert r.status_code == 200
    listed = client.get("/api/qa/repos").json()
    names = [row["repo"] for row in listed["repos"]]
    assert "api/org" in names
    r2 = client.delete("/api/qa/repos/api%2Forg")
    assert r2.status_code == 200
