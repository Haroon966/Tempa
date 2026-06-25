"""Tests for QA findings store."""

from tempa.qa.store import (
    add_finding,
    compute_grade,
    get_finding,
    list_branch_statuses,
    list_findings,
    summary_stats,
    upsert_branch_status,
)


def test_add_and_list_findings():
    f = add_finding(
        repo="org/repo",
        branch="main",
        category="lint_error",
        severity="medium",
        title="Ruff E501",
    )
    assert f["id"]
    items = list_findings(repo="org/repo")
    assert any(i["id"] == f["id"] for i in items)
    loaded = get_finding(f["id"])
    assert loaded is not None
    assert loaded["title"] == "Ruff E501"


def test_branch_status_and_grade():
    upsert_branch_status(
        "org/repo",
        "dev",
        ci_status="failure",
        lint_status="success",
        test_status="failure",
        security_count=2,
        finding_count=3,
        grade="D",
    )
    branches = list_branch_statuses(repo="org/repo")
    assert len(branches) == 1
    assert branches[0]["grade"] == "D"
    assert compute_grade(ci_status="success", lint_status="success", test_status="success", security_count=0, finding_count=0) == "A"


def test_summary_stats():
    stats = summary_stats()
    assert "repos_monitored" in stats
    assert "queue_depth" in stats
