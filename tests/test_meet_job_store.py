from __future__ import annotations

import json
from pathlib import Path

import pytest

from tempa.meet import job_store


@pytest.fixture(autouse=True)
def _isolated_meet_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    meet_dir = tmp_path / "meet"
    meet_dir.mkdir()
    queue_path = meet_dir / "job_queue.jsonl"
    status_path = meet_dir / "job_status.json"
    monkeypatch.setattr(job_store, "_queue_path", lambda: queue_path)
    monkeypatch.setattr(job_store, "_status_path", lambda: status_path)
    yield


def _write_queue(*rows: dict) -> None:
    path = job_store._queue_path()
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_claim_next_job_picks_newest_and_dedupes_url():
    _write_queue(
        {
            "id": "old",
            "meet_url": "https://meet.google.com/abc-defg-hij",
            "title": "Old",
            "enqueued_at": "2026-06-18T14:00:00+00:00",
            "status": "queued",
        },
        {
            "id": "new",
            "meet_url": "https://meet.google.com/abc-defg-hij",
            "title": "New",
            "enqueued_at": "2026-06-18T15:00:00+00:00",
            "status": "queued",
        },
        {
            "id": "other",
            "meet_url": "https://meet.google.com/xyz-uvwx-rst",
            "title": "Other",
            "enqueued_at": "2026-06-18T14:30:00+00:00",
            "status": "queued",
        },
    )
    claimed = job_store.claim_next_job()
    assert claimed is not None
    assert claimed["id"] == "new"

    remaining = job_store._parse_queue_lines(
        job_store._queue_path().read_text(encoding="utf-8").splitlines()
    )
    remaining_ids = {row["id"] for row in remaining}
    assert "old" not in remaining_ids
    assert "other" in remaining_ids

    statuses = job_store.get_all_job_statuses()
    assert statuses["old"]["status"] == "skipped"
    assert statuses["new"]["status"] == "running"


def test_recover_stale_running_job_skips_when_newer_queued():
    _write_queue(
        {
            "id": "queued-new",
            "meet_url": "https://meet.google.com/live-meet",
            "title": "Live",
            "enqueued_at": "2026-06-18T15:00:00+00:00",
            "status": "queued",
        }
    )
    status_path = job_store._status_path()
    status_path.write_text(
        json.dumps(
            {
                "stale-running": {
                    "status": "running",
                    "meet_url": "https://meet.google.com/live-meet",
                    "title": "Live",
                }
            }
        ),
        encoding="utf-8",
    )

    recovered = job_store.recover_stale_running_jobs()
    assert recovered == 0
    statuses = job_store.get_all_job_statuses()
    assert statuses["stale-running"]["status"] == "failed"
