from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from tempa.meet.capture_slots import CaptureSlot, CaptureSlotPool
from tempa.meet.job_store import claim_next_job, update_job_status
from tempa.meet.service import build_worker_config, run_meeting_job_sync
from tempa.settings import get_settings

logger = logging.getLogger(__name__)


async def _run_claimed_job(job: dict[str, Any], slot: CaptureSlot, *, pool: CaptureSlotPool) -> None:
    meeting_id = str(job["id"])
    meet_url = str(job["meet_url"])
    title = str(job.get("title") or "")
    notify = job.get("notify_number")
    av_test_url = job.get("av_test_youtube_url")
    if av_test_url and not get_settings().meet_av_test_enabled:
        logger.warning("Meet worker ignoring av_test_youtube_url (MEET_AV_TEST_ENABLED=false)")
        av_test_url = None
    try:
        logger.info(
            "Meet worker claimed job %s for %s (slot=%s display=%s)",
            meeting_id,
            meet_url,
            slot.index,
            slot.display,
        )
        config = build_worker_config(
            meet_url,
            meeting_id,
            duration_seconds=int(job.get("duration_seconds") or 3600),
            calendar_event_id=job.get("calendar_event_id"),
            calendar_event_start=job.get("calendar_event_start"),
            calendar_event_end=job.get("calendar_event_end"),
            attendee_emails=job.get("attendee_emails"),
            organizer_email=job.get("organizer_email"),
            av_test_youtube_url=av_test_url,
            display=slot.display,
            pulse_sink=slot.pulse_sink,
            pulse_monitor_source=slot.pulse_monitor,
        )
        await asyncio.to_thread(
            run_meeting_job_sync,
            config,
            title=title,
            notify_number=str(notify) if notify else None,
        )
    except Exception as exc:
        logger.exception("Meet worker job failed: %s", meeting_id)
        update_job_status(meeting_id, status="failed", error=str(exc))
    finally:
        pool.release(slot)


def _drain_finished(in_flight: dict[str, asyncio.Task[None]]) -> None:
    for meeting_id, task in list(in_flight.items()):
        if not task.done():
            continue
        in_flight.pop(meeting_id, None)
        try:
            task.result()
        except Exception:
            logger.exception("Meet worker task error for %s", meeting_id)


async def _poll_loop() -> None:
    from tempa.meet.worker_heartbeat import write_worker_heartbeat

    settings = get_settings()
    max_concurrent = settings.meet_max_concurrent
    pool = CaptureSlotPool(max_concurrent)
    in_flight: dict[str, asyncio.Task[None]] = {}
    poll_seconds = float(os.environ.get("TEMPA_MEET_WORKER_POLL_SECONDS", "3"))
    ticks = 0
    logger.info("Meet worker pool size=%s", pool.size)

    while True:
        write_worker_heartbeat(pid=os.getpid())
        ticks += 1
        _drain_finished(in_flight)

        if ticks % 20 == 0:
            from tempa.meet.job_store import recover_stale_running_jobs

            stale = recover_stale_running_jobs(max_age_minutes=10, active_meeting_ids=set(in_flight))
            if stale:
                logger.info("Cleared %s stale meet job(s) during poll", stale)

        while len(in_flight) < max_concurrent:
            slot = pool.try_acquire()
            if slot is None:
                break
            job = claim_next_job()
            if not job:
                pool.release(slot)
                break
            meeting_id = str(job["id"])
            task = asyncio.create_task(
                _run_claimed_job(job, slot, pool=pool),
                name=f"meet-job-{meeting_id}",
            )
            in_flight[meeting_id] = task

        await asyncio.sleep(poll_seconds)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
    )
    from tempa.settings import get_settings

    get_settings().ensure_dirs()
    from tempa.meet.job_store import list_interrupted_job_ids, recover_stale_running_jobs

    recovered = recover_stale_running_jobs(on_startup=True)
    if recovered:
        logger.info("Marked %s orphaned meet job(s) interrupted for finalize", recovered)

    interrupted = list_interrupted_job_ids()
    if interrupted:
        logger.info("Finalizing %s interrupted meet job(s)", len(interrupted))
        asyncio.run(_finalize_interrupted_jobs(interrupted))

    logger.info(
        "Meet worker started (poll=%ss max_concurrent=%s)",
        os.environ.get("TEMPA_MEET_WORKER_POLL_SECONDS", "3"),
        get_settings().meet_max_concurrent,
    )
    asyncio.run(_poll_loop())


async def _finalize_interrupted_jobs(job_ids: list[str]) -> None:
    from tempa.meet.service import repair_meeting_finalize

    for meeting_id in job_ids:
        try:
            await repair_meeting_finalize(meeting_id, send_notifications=False)
            logger.info("Finalized interrupted meet job %s", meeting_id)
        except Exception:
            logger.exception("Failed to finalize interrupted meet job %s", meeting_id)
            update_job_status(
                meeting_id,
                status="failed",
                error="interrupted finalize failed",
                leave_reason="worker_interrupted",
            )


if __name__ == "__main__":
    main()
