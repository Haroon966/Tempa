"""QA background worker."""

from __future__ import annotations

import asyncio
import logging

from tempa.qa.config import qa_enabled
from tempa.qa.job_store import claim_next_job, update_job_status
from tempa.qa.scanner import scan_all_branches_for_repo, scan_branch

log = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None


async def _process_job(job: dict) -> None:
    job_id = str(job.get("id") or "")
    repo = str(job.get("repo") or "")
    branch = job.get("branch")
    job_type = str(job.get("job_type") or "branch_scan")
    installation_id = job.get("installation_id")
    inst_id = int(installation_id) if installation_id else None

    try:
        if job_type == "repo_scan":
            ids = scan_all_branches_for_repo(repo, installation_id=inst_id)
            update_job_status(job_id, status="completed", result={"enqueued": len(ids)})
            return

        if job_type == "deep_review":
            update_job_status(
                job_id,
                status="completed",
                result={
                    "message": "Use Claude Code or Cursor with agent-playbook API",
                    "hint": f"GET /api/qa/findings/<id>/agent-playbook?target=claude",
                },
            )
            return

        if not branch:
            ids = scan_all_branches_for_repo(repo, installation_id=inst_id)
            update_job_status(job_id, status="completed", result={"enqueued": len(ids)})
            return

        result = await asyncio.to_thread(
            scan_branch,
            repo,
            str(branch),
            installation_id=inst_id,
            scan_job_id=job_id,
        )
        update_job_status(job_id, status="completed", result=result)
    except Exception as exc:
        log.exception("QA job failed %s", job_id)
        update_job_status(job_id, status="failed", error=str(exc))


async def _poll_loop() -> None:
    from tempa.settings import get_settings

    poll_seconds = max(5, get_settings().tempa_qa_scan_interval_minutes * 60 // 10)
    while True:
        job = None
        if qa_enabled():
            job = claim_next_job()
            if job:
                await _process_job(job)
        await asyncio.sleep(0.5 if job else poll_seconds)


async def _scheduled_scan_loop() -> None:
    from tempa.qa.installations import list_repos
    from tempa.qa.job_store import enqueue_scan
    from tempa.settings import get_settings

    interval = max(5, get_settings().tempa_qa_scan_interval_minutes) * 60
    while True:
        await asyncio.sleep(interval)
        if not qa_enabled():
            continue
        for repo in list_repos():
            try:
                enqueue_scan(repo, job_type="repo_scan")
            except Exception:
                log.exception("scheduled scan enqueue failed for %s", repo)


async def start_qa_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_poll_loop(), name="qa-worker")
    asyncio.create_task(_scheduled_scan_loop(), name="qa-scheduled-scan")


async def stop_qa_worker() -> None:
    global _worker_task
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
