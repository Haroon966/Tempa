"""Interrupted job recovery marks jobs for finalize."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from tempa.meet.job_store import list_interrupted_job_ids, recover_stale_running_jobs


def test_startup_recovery_marks_interrupted(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    meet_dir = get_settings().sessions_dir / "meet"
    meet_dir.mkdir(parents=True)
    status_path = meet_dir / "job_status.json"
    status_path.write_text(
        json.dumps(
            {
                "job-1": {
                    "status": "running",
                    "meet_url": "https://meet.google.com/abc-defg-hij",
                    "title": "Standup",
                    "started_at": "2026-07-22T10:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )
    (meet_dir / "job_queue.jsonl").write_text("", encoding="utf-8")

    recovered = recover_stale_running_jobs(on_startup=True)
    assert recovered == 1
    data = json.loads(status_path.read_text(encoding="utf-8"))
    assert data["job-1"]["status"] == "interrupted"
    assert data["job-1"]["leave_reason"] == "worker_interrupted"
    assert list_interrupted_job_ids() == ["job-1"]
