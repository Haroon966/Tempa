"""Tests for QA API endpoints."""

from tempa.qa.installations import upsert_installation
from tempa.qa.store import add_finding, upsert_branch_status


def test_qa_summary(client):
    r = client.get("/api/qa/summary")
    assert r.status_code == 200
    data = r.json()
    assert "enabled" in data
    assert "groq_configured" in data


def test_qa_agent_playbook_endpoint(client):
    record = add_finding(
        repo="test-org/tempa",
        branch="main",
        severity="high",
        category="lint",
        title="unused import",
        file="src/tempa/foo.py",
    )
    fid = record["id"]
    r = client.get(f"/api/qa/findings/{fid}/agent-playbook?target=claude")
    assert r.status_code == 200
    data = r.json()
    assert data["finding_id"] == fid
    assert "curl" in data["prompt"]
    assert data["terminal_command"]


def test_qa_branches_and_findings(client):
    upsert_installation(1, "test-org", [{"full_name": "test-org/tempa", "id": 1}])
    upsert_branch_status("test-org/tempa", "main", grade="B", ci_status="success")
    add_finding(
        repo="test-org/tempa",
        branch="main",
        severity="high",
        category="test_failure",
        title="pytest failed",
    )

    branches = client.get("/api/qa/branches").json()
    assert any(b["branch"] == "main" for b in branches["branches"])

    findings = client.get("/api/qa/findings").json()
    assert len(findings["findings"]) >= 1


def test_qa_scan_enqueue(client):
    upsert_installation(2, "org", [{"full_name": "org/app", "id": 2}])
    r = client.post("/api/qa/scan", json={"repo": "org/app"})
    assert r.status_code == 200
    assert r.json()["status"] == "queued"
    jobs = client.get("/api/qa/jobs").json()
    assert len(jobs["jobs"]) >= 1


def test_qa_spa_route(client):
    r = client.get("/qa")
    assert r.status_code in (200, 404)
