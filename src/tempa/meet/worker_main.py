from __future__ import annotations

import asyncio
import logging
import os
import time

from tempa.meet.job_store import claim_next_job, update_job_status
from tempa.meet.service import build_worker_config, run_meeting_job_sync

logger = logging.getLogger(__name__)


async def _poll_loop() -> None:
    poll_seconds = float(os.environ.get("TEMPA_MEET_WORKER_POLL_SECONDS", "3"))
    while True:
        job = claim_next_job()
        if job:
            meeting_id = str(job["id"])
            meet_url = str(job["meet_url"])
            title = str(job.get("title") or "")
            notify = job.get("notify_number")
            logger.info("Meet worker claimed job %s for %s", meeting_id, meet_url)
            try:
                config = build_worker_config(meet_url, meeting_id)
                await asyncio.to_thread(
                    run_meeting_job_sync,
                    config,
                    title=title,
                    notify_number=str(notify) if notify else None,
                )
                update_job_status(meeting_id, status="completed")
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

    recovered = recover_stale_running_jobs()
    if recovered:
        logger.info("Re-queued %s stale meet job(s)", recovered)
    logger.info("Meet worker started (poll=%ss)", os.environ.get("TEMPA_MEET_WORKER_POLL_SECONDS", "3"))
    asyncio.run(_poll_loop())


if __name__ == "__main__":
    main()
