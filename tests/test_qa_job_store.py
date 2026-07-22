"""QA job queue: reclaim orphans and fan-out metadata."""

import json
from pathlib import Path

from tempa.qa import job_store
from tempa.qa.scanner import scan_all_branches_for_repo


def _isolate(tmp_path: Path, monkeypatch):
    qa_dir = tmp_path / "qa"
    qa_dir.mkdir()
    monkeypatch.setattr(job_store, "_queue_path", lambda: qa_dir / "job_queue.jsonl")
    monkeypatch.setattr(job_store, "_status_path", lambda: qa_dir / "job_status.json")
    return qa_dir


def test_recover_stale_running_jobs_requeues_on_startup(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    job_id = job_store.enqueue_scan("org/repo", branch="feat", job_type="branch_scan")
    claimed = job_store.claim_next_job()
    assert claimed is not None
    assert claimed["id"] == job_id
    assert job_store.list_jobs(limit=1)[0]["status"] == "running"
    assert job_store.queue_depth() == 0

    n = job_store.recover_stale_running_jobs(on_startup=True)
    assert n == 1
    assert job_store.queue_depth() == 1
    row = job_store.list_jobs(limit=1)[0]
    assert row["status"] == "queued"
    assert row.get("reclaimed_at")
    assert "started_at" not in row


def test_recover_stale_running_jobs_noop_when_not_startup(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    job_store.enqueue_scan("org/repo", branch="feat")
    job_store.claim_next_job()
    assert job_store.recover_stale_running_jobs(on_startup=False) == 0
    assert job_store.list_jobs(limit=1)[0]["status"] == "running"


def test_scan_all_branches_propagates_requester(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr("tempa.qa.scanner.installation_id_for_repo", lambda repo: 1)
    monkeypatch.setattr("tempa.qa.scanner.github_uses_pat", lambda: False)
    monkeypatch.setattr("tempa.qa.scanner.get_github_token", lambda repo: "tok")
    monkeypatch.setattr(
        "tempa.qa.scanner.list_repo_branches",
        lambda repo, token: [{"name": "main"}, {"name": "feat"}],
    )

    ids = scan_all_branches_for_repo(
        "org/repo",
        installation_id=1,
        extra={"requested_by": "scheduler", "source_channel": "scheduler"},
    )
    assert len(ids) == 2
    jobs = {j["id"]: j for j in job_store.list_jobs(limit=10)}
    for jid in ids:
        assert jobs[jid]["requested_by"] == "scheduler"
        assert jobs[jid]["source_channel"] == "scheduler"
        assert jobs[jid]["job_type"] == "branch_scan"


def test_failed_job_sets_completed_at(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    job_id = job_store.enqueue_scan("org/repo", branch="feat")
    job_store.update_job_status(job_id, status="failed", error="boom")
    row = json.loads((tmp_path / "qa" / "job_status.json").read_text())[job_id]
    assert row["status"] == "failed"
    assert row.get("completed_at")


def test_drop_queued_jobs_by_source(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    keep = job_store.enqueue_scan(
        "org/keep",
        branch="main",
        extra={"source_channel": "slack", "requested_by": "U1"},
    )
    job_store.enqueue_scan(
        "org/drop",
        branch="feat",
        extra={"source_channel": "scheduler", "requested_by": "scheduler"},
    )
    job_store.enqueue_scan(
        "org/drop2",
        branch="feat2",
        extra={"source_channel": "scheduler", "requested_by": "scheduler"},
    )
    assert job_store.queue_depth() == 3
    n = job_store.drop_queued_jobs(source_channel="scheduler")
    assert n == 2
    assert job_store.queue_depth() == 1
    remaining = job_store.claim_next_job()
    assert remaining and remaining["id"] == keep
    statuses = {j["id"]: j for j in job_store.list_jobs(limit=10)}
    assert statuses[keep]["status"] == "running"
    assert sum(1 for j in statuses.values() if j.get("status") == "cancelled") == 2
