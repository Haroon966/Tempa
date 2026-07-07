from __future__ import annotations

import asyncio
import logging
import os
import time

from tempa.meet.job_store import claim_next_job, update_job_status
from tempa.meet.service import build_worker_config, run_meeting_job_sync
from tempa.settings import get_settings

logger = logging.getLogger(__name__)


async def _poll_loop() -> None:
    from tempa.meet.worker_heartbeat import write_worker_heartbeat

    poll_seconds = float(os.environ.get("TEMPA_MEET_WORKER_POLL_SECONDS", "3"))
    ticks = 0
    while True:
        write_worker_heartbeat(pid=os.getpid())
        ticks += 1
        if ticks % 20 == 0:
            from tempa.meet.job_store import recover_stale_running_jobs

            stale = recover_stale_running_jobs(max_age_minutes=10)
            if stale:
                logger.info("Cleared %s stale meet job(s) during poll", stale)
        job = claim_next_job()
        if job:
            meeting_id = str(job["id"])
            meet_url = str(job["meet_url"])
            title = str(job.get("title") or "")
            notify = job.get("notify_number")
            av_test_url = job.get("av_test_youtube_url")
            if av_test_url and not get_settings().meet_av_test_enabled:
                logger.warning("Meet worker ignoring av_test_youtube_url (MEET_AV_TEST_ENABLED=false)")
                av_test_url = None
            logger.info("Meet worker claimed job %s for %s", meeting_id, meet_url)
            try:
                config = build_worker_config(
                    meet_url,
                    meeting_id,
                    duration_seconds=int(job.get("duration_seconds") or 3600),
                    calendar_event_id=job.get("calendar_event_id"),
                    calendar_event_start=job.get("calendar_event_start"),
                    calendar_event_end=job.get("calendar_event_end"),
                    attendee_emails=job.get("attendee_emails"),
                    av_test_youtube_url=av_test_url,
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
        await asyncio.sleep(poll_seconds)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
    )
    from tempa.settings import get_settings

    get_settings().ensure_dirs()
    from tempa.meet.job_store import recover_stale_running_jobs

    recovered = recover_stale_running_jobs(on_startup=True)
    if recovered:
        logger.info("Cleared %s orphaned meet job(s) from prior worker session", recovered)
    logger.info("Meet worker started (poll=%ss)", os.environ.get("TEMPA_MEET_WORKER_POLL_SECONDS", "3"))
    asyncio.run(_poll_loop())


if __name__ == "__main__":
    main()
