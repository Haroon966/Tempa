"""QA background worker."""

from __future__ import annotations

import asyncio
import logging

from tempa.qa.config import load_qa_config, qa_enabled
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
            from tempa.qa.deep_review.lite import run_deep_review
            from tempa.qa.github.assign import ensure_pr_assignee

            pr_number = int(job.get("pr_number") or 0)
            # Rule: before reviewing, ensure the PR has an assignee.
            assign_info = await asyncio.to_thread(ensure_pr_assignee, repo, pr_number)

            result = await run_deep_review(
                repo,
                pr_number,
                installation_id=inst_id,
                scan_job_id=job_id,
            )
            result["assign"] = assign_info

            # One request yields review + tests: scan the PR head branch in the same job
            # so lint/pytest/security findings land in the same comment.
            branch_name = str(result.get("branch") or "")
            branch_status: dict | None = None
            if branch_name:
                try:
                    scan_result = await asyncio.to_thread(
                        scan_branch,
                        repo,
                        branch_name,
                        installation_id=inst_id,
                        scan_job_id=job_id,
                    )
                    branch_status = scan_result.get("branch_status")
                    result["grade"] = scan_result.get("grade")
                    result["scan_finding_count"] = scan_result.get("finding_count")
                except Exception:
                    log.exception("QA branch scan failed during deep review %s", job_id)

            if load_qa_config().get("auto_comment_on_pr", True):
                from tempa.qa.comments import post_review_summary
                from tempa.qa.store import list_findings

                findings = list_findings(scan_job_id=job_id, status=None, limit=100)
                try:
                    posted = await asyncio.to_thread(
                        post_review_summary,
                        repo,
                        pr_number,
                        findings,
                        branch_status=branch_status,
                    )
                    result["comment_url"] = posted.get("url", "")
                except Exception:
                    log.exception("QA review comment failed for %s", job_id)

            update_job_status(job_id, status="completed", result=result)
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
    # Queue poll is independent of scheduled full-repo scans — keep it snappy.
    poll_seconds = 5
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
                enqueue_scan(
                    repo,
                    job_type="repo_scan",
                    extra={"requested_by": "scheduler", "source_channel": "scheduler"},
                )
            except Exception:
                log.exception("scheduled scan enqueue failed for %s", repo)


async def start_qa_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    try:
        from tempa.qa.github.sync_installations import sync_app_installations

        n = await asyncio.to_thread(sync_app_installations)
        log.info("QA synced %s GitHub App installation(s)", n)
    except Exception:
        log.exception("QA GitHub App sync failed")
    _worker_task = asyncio.create_task(_poll_loop(), name="qa-worker")
    asyncio.create_task(_scheduled_scan_loop(), name="qa-scheduled-scan")
    log.info("QA worker poll loop started")


async def stop_qa_worker() -> None:
    global _worker_task
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
