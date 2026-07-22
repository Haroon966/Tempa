from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from tempa.meet.capture_slots import CaptureSlotPool, slot_for_index
from tempa.meet import job_store
from tempa.meet import worker_main


def test_slot_for_index_names():
    s0 = slot_for_index(0)
    assert s0.display == ":99"
    assert s0.pulse_sink == "meet_sink_0"
    assert s0.pulse_monitor == "meet_sink_0.monitor"
    s1 = slot_for_index(1)
    assert s1.display == ":100"
    assert s1.pulse_sink == "meet_sink_1"


@pytest.mark.asyncio
async def test_capture_slot_pool_acquire_release_capacity():
    pool = CaptureSlotPool(2)
    assert pool.size == 2
    assert pool.available == 2

    a = pool.try_acquire()
    b = pool.try_acquire()
    assert a is not None and b is not None
    assert a.index != b.index
    assert pool.try_acquire() is None
    assert pool.available == 0

    pool.release(a)
    assert pool.available == 1
    c = pool.try_acquire()
    assert c is not None
    assert c.index == a.index


@pytest.mark.asyncio
async def test_poll_loop_respects_max_concurrent(monkeypatch: pytest.MonkeyPatch):
    claimed: list[str] = []
    jobs = [
        {"id": "j1", "meet_url": "https://meet.google.com/aaa-bbbb-ccc", "title": "A"},
        {"id": "j2", "meet_url": "https://meet.google.com/ddd-eeee-fff", "title": "B"},
        {"id": "j3", "meet_url": "https://meet.google.com/ggg-hhhh-iii", "title": "C"},
    ]

    def fake_claim():
        return jobs.pop(0) if jobs else None

    async def fake_run(job, slot, *, pool):
        claimed.append(str(job["id"]))
        await asyncio.sleep(0.2)
        pool.release(slot)

    class _Settings:
        meet_max_concurrent = 2
        meet_av_test_enabled = False

    monkeypatch.setattr(worker_main, "claim_next_job", fake_claim)
    monkeypatch.setattr(worker_main, "_run_claimed_job", fake_run)
    monkeypatch.setattr(worker_main, "get_settings", lambda: _Settings())
    import tempa.meet.worker_heartbeat as hb

    monkeypatch.setattr(hb, "write_worker_heartbeat", lambda **_: None)
    monkeypatch.setenv("TEMPA_MEET_WORKER_POLL_SECONDS", "0.05")

    task = asyncio.create_task(worker_main._poll_loop())
    await asyncio.sleep(0.12)
    assert set(claimed) == {"j1", "j2"}
    assert "j3" not in claimed
    await asyncio.sleep(0.25)
    assert set(claimed) == {"j1", "j2", "j3"}
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_recover_skips_active_meeting_ids(tmp_path, monkeypatch: pytest.MonkeyPatch):
    meet_dir = tmp_path / "meet"
    meet_dir.mkdir()
    monkeypatch.setattr(job_store, "_queue_path", lambda: meet_dir / "job_queue.jsonl")
    monkeypatch.setattr(job_store, "_status_path", lambda: meet_dir / "job_status.json")

    old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    job_store._status_path().write_text(
        __import__("json").dumps(
            {
                "live": {
                    "status": "running",
                    "meet_url": "https://meet.google.com/live-meet",
                    "title": "Live",
                    "started_at": old,
                },
                "orphan": {
                    "status": "running",
                    "meet_url": "https://meet.google.com/dead-meet",
                    "title": "Orphan",
                    "started_at": old,
                },
            }
        ),
        encoding="utf-8",
    )
    job_store._queue_path().write_text("", encoding="utf-8")

    recovered = job_store.recover_stale_running_jobs(
        max_age_minutes=10,
        active_meeting_ids={"live"},
    )
    assert recovered == 1
    statuses = job_store.get_all_job_statuses()
    assert statuses["live"]["status"] == "running"
    assert statuses["orphan"]["status"] == "queued"


def test_meet_max_concurrent_clamped(monkeypatch: pytest.MonkeyPatch):
    from tempa.settings import Settings

    assert Settings(meet_max_concurrent=0).meet_max_concurrent == 1
    assert Settings(meet_max_concurrent=99).meet_max_concurrent == 16
    assert Settings(meet_max_concurrent=10).meet_max_concurrent == 10
    assert Settings(meet_max_concurrent=3).meet_max_concurrent == 3
