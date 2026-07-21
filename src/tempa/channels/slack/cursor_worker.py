"""Parallel Cursor job worker for pinned Slack threads."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from tempa.channels.slack import cursor_jobs as jobs
from tempa.channels.slack import cursor_pr as cpr
from tempa.channels.slack import cursor_progress as prog
from tempa.channels.slack import cursor_qa as cqa
from tempa.channels.slack import cursor_worktree as wt
from tempa.qa.cursor import cursor_configured, cursor_prompt
from tempa.settings import get_settings

log = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None


def _post(channel_id: str, thread_ts: str, text: str) -> None:
    from tempa.channels.slack.outbound import send_slack_message_sync

    try:
        send_slack_message_sync(channel_id, text, thread_ts=thread_ts, source_channel="cursor_job")
    except Exception:
        log.exception("cursor worker slack post failed")


async def _progress_ticker(job_id: str, channel_id: str, thread_ts: str, stop: asyncio.Event) -> None:
    settings = get_settings()
    interval = max(30, int(settings.tempa_cursor_progress_interval_sec or 120))
    started = time.time()
    n = 0
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass
        row = jobs.get_job(job_id) or {}
        status = str(row.get("status") or "")
        if status not in jobs.ACTIVE_STATUSES:
            break
        n += 1
        elapsed_m = max(1, int((time.time() - started) / 60))
        phase = str(row.get("phase") or "")
        if phase in {"waiting_ci", "fixing_ci"}:
            msg = prog.msg_waiting_ci() if phase == "waiting_ci" else prog.msg_ci_red()
        else:
            msg = prog.msg_still_working(elapsed_m)
        await asyncio.to_thread(_post, channel_id, thread_ts, msg)
        jobs.update_job(job_id, last_progress_at=jobs._now_iso())
        if n >= 20:
            break


def _build_agent_prompt(job: dict[str, Any], *, comments: str = "", ci_logs: str = "") -> str:
    import os

    parts = [
        "You are Tempa working a Slack engineering request via Cursor.",
        f"Requester Slack user: {job.get('user_id')}",
        f"Mode: {job.get('mode')}",
        "Rules: Do not merge PRs. Do not combine this work into another user's PR or branch. "
        "Prefer facts. If fixing code, commit and push only on THIS job's branch.",
    ]
    if job.get("worktree_path"):
        parts.append(f"Working directory: {job['worktree_path']}")
    if job.get("branch"):
        parts.append(f"Branch: {job['branch']}")
    if job.get("pr_url"):
        parts.append(f"PR: {job['pr_url']}")
    test_env = os.environ.get("TEMPA_CURSOR_TEST_ENV_FILE", "").strip()
    if test_env:
        parts.append(
            f"Test credentials/context file (use when running tests the user asked for): {test_env}"
        )
    if comments:
        parts.append("PR comments to address:\n" + comments[:6000])
    if ci_logs:
        parts.append("CI failure logs:\n" + ci_logs[:8000])
    parts.append("User request:\n" + str(job.get("ask_text") or ""))
    return "\n\n".join(parts)


async def _run_agent(job: dict[str, Any], *, comments: str = "", ci_logs: str = "") -> str:
    prompt = _build_agent_prompt(job, comments=comments, ci_logs=ci_logs)
    cwd = str(job.get("worktree_path") or job.get("local_cwd") or "")
    timeout = max(60, int(get_settings().tempa_cursor_job_timeout_sec or 900))
    return await asyncio.wait_for(
        cursor_prompt(
            prompt,
            repo=str(job.get("repo") or ""),
            starting_ref=job.get("starting_ref"),
            local_cwd=cwd,
        ),
        timeout=timeout,
    )


async def _process_job(job: dict[str, Any]) -> None:
    job_id = str(job.get("id") or "")
    channel_id = str(job.get("channel_id") or "")
    thread_ts = str(job.get("thread_ts") or "")
    ask = str(job.get("ask_text") or "")
    stop = asyncio.Event()
    ticker = asyncio.create_task(_progress_ticker(job_id, channel_id, thread_ts, stop))

    try:
        settings = get_settings()
        mode = str(job.get("mode") or "read")
        local_cwd = str(job.get("local_cwd") or "")
        required = list(job.get("required_checks") or ["backend-ci", "frontend-ci", "e2e"])
        base_ref = str(job.get("base_ref") or "main")
        jira_key = str(job.get("jira_key") or "").strip() or None
        repo = str(job.get("repo") or "")

        adopted = cpr.parse_pr_url(ask)
        worktree_path = ""
        branch = ""
        pr_url = ""
        pr_number: int | None = None
        jira_key = cqa.extract_jira_key(ask, jira_key)

        if mode == "write" or adopted:
            if not local_cwd:
                raise RuntimeError("local_cwd required for write/QA jobs")
            if not wt.git_available():
                raise RuntimeError("git is not available in the Tempa environment")
            if adopted:
                pr_url = str(adopted["pr_url"])
                pr_number = int(adopted["pr_number"])
                repo = str(adopted.get("full_repo") or repo)
                head = await asyncio.to_thread(
                    cpr.pr_head_ref,
                    pr_number,
                    cwd=local_cwd,
                    repo=repo,
                )
                branch = str(head.get("branch") or "")
                if head.get("pr_url"):
                    pr_url = str(head["pr_url"])
                if not branch:
                    raise RuntimeError(f"could not resolve head branch for PR #{pr_number}")
                worktree_path = str(
                    await asyncio.to_thread(
                        wt.ensure_worktree,
                        repo_cwd=local_cwd,
                        branch=branch,
                        job_id=job_id,
                        starting_ref=branch,
                    )
                )
            else:
                binding = jobs.find_pr_binding(
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    user_id=str(job.get("user_id") or ""),
                    repo=repo,
                )
                if binding and binding.get("branch"):
                    branch = str(binding["branch"])
                    pr_url = str(binding.get("pr_url") or "")
                    pr_number = binding.get("pr_number")
                    if isinstance(pr_number, str) and pr_number.isdigit():
                        pr_number = int(pr_number)
                else:
                    branch = wt.branch_name(
                        user_id=str(job.get("user_id") or "user"),
                        thread_ts=thread_ts,
                        job_id=job_id,
                    )
                worktree_path = str(
                    await asyncio.to_thread(
                        wt.ensure_worktree,
                        repo_cwd=local_cwd,
                        branch=branch,
                        job_id=job_id,
                        starting_ref=job.get("starting_ref"),
                    )
                )

            jobs.update_job(
                job_id,
                worktree_path=worktree_path,
                branch=branch,
                pr_url=pr_url or None,
                pr_number=pr_number,
                phase="running",
                status="running",
            )
            job = {**job, "worktree_path": worktree_path, "branch": branch, "pr_url": pr_url, "pr_number": pr_number}

            reply = await _run_agent(job)

            if cqa.wants_tests(ask) and worktree_path:
                jobs.update_job(job_id, phase="running_tests", status="running_tests")
                if not job.get("asked_test_creds"):
                    missing = cqa.missing_test_context_message(cwd=worktree_path, ask_text=ask)
                    if missing:
                        _post(channel_id, thread_ts, missing)
                        jobs.update_job(job_id, asked_test_creds=True)
                        job["asked_test_creds"] = True
                test_out = await asyncio.to_thread(cqa.run_local_tests, worktree_path)
                failed_local = any(
                    line.startswith("exit=") and line != "exit=0" for line in (test_out or "").splitlines()
                )
                if failed_local:
                    reply = await _run_agent(job, ci_logs=test_out)

            # Ensure PR exists for write path
            if mode == "write" and not pr_number and not adopted:
                try:
                    await asyncio.to_thread(cpr.push_branch, cwd=worktree_path, branch=branch)
                    created = await asyncio.to_thread(
                        cpr.create_pr,
                        cwd=worktree_path,
                        title=f"tempa: {ask[:80]}",
                        body=(
                            f"Opened by Tempa for Slack user `{job.get('user_id')}`.\n"
                            f"Thread: {thread_ts}\n\nDo not combine with other Tempa PRs.\n\n{ask[:2000]}"
                        ),
                        base=base_ref,
                        head=branch,
                    )
                    pr_url = str(created.get("pr_url") or "")
                    pr_number = created.get("pr_number")
                    jobs.update_job(job_id, pr_url=pr_url, pr_number=pr_number)
                    job["pr_url"] = pr_url
                    job["pr_number"] = pr_number
                    _post(
                        channel_id,
                        thread_ts,
                        f"_Tempa finished the code changes and opened/updated <{pr_url}> for you. Waiting for CI…_",
                    )
                except Exception as exc:
                    log.warning("pr create skipped/failed: %s", exc)

            # CI / comments loop — never mark completed while required CI is red/pending.
            last_ci: dict[str, Any] = {}
            if pr_number:
                max_fix = max(1, int(settings.tempa_cursor_ci_fix_max or 3))
                timeout_sec = max(120, int(settings.tempa_cursor_job_timeout_sec or 900))
                deadline = time.time() + timeout_sec
                fix_count = 0
                while True:
                    jobs.update_job(
                        job_id,
                        phase="waiting_ci",
                        status="waiting_ci",
                        ci_fix_count=fix_count,
                    )
                    summary = await asyncio.to_thread(
                        cqa.evaluate_ci,
                        pr_number=int(pr_number),
                        cwd=worktree_path,
                        repo=repo,
                        required_checks=required,
                    )
                    last_ci = summary
                    comments = await asyncio.to_thread(
                        cqa.collect_comment_blockers,
                        pr_number=int(pr_number),
                        cwd=worktree_path,
                        repo=repo,
                    )
                    status = summary.get("status")
                    if status == "green":
                        break

                    if status == "pending":
                        if time.time() >= deadline:
                            jobs.update_job(job_id, status="needs_help", phase="needs_help")
                            help_msg = (
                                f"_Tempa is still waiting on CI for <{pr_url}> after "
                                f"{timeout_sec // 60}m — needs a human look._"
                            )
                            await asyncio.to_thread(
                                cqa.notify_done,
                                summary=help_msg + "\n\n" + str(summary),
                                channel_id=channel_id,
                                thread_ts=thread_ts,
                                ask_text=ask,
                                pr_number=int(pr_number),
                                pr_url=pr_url,
                                repo=repo,
                                cwd=worktree_path,
                                jira_key=jira_key,
                                user_id=str(job.get("user_id") or ""),
                            )
                            return
                        _post(channel_id, thread_ts, prog.msg_waiting_ci())
                        await asyncio.sleep(45)
                        continue

                    # red or actionable comments
                    actionable = status == "red" or bool(comments.strip())
                    if not actionable:
                        break
                    if fix_count >= max_fix:
                        jobs.update_job(job_id, status="needs_help", phase="needs_help")
                        help_msg = prog.msg_needs_help(pr_url=pr_url, attempts=max_fix)
                        await asyncio.to_thread(
                            cqa.notify_done,
                            summary=help_msg + "\n\n" + str(summary),
                            channel_id=channel_id,
                            thread_ts=thread_ts,
                            ask_text=ask,
                            pr_number=int(pr_number),
                            pr_url=pr_url,
                            repo=repo,
                            cwd=worktree_path,
                            jira_key=jira_key,
                            user_id=str(job.get("user_id") or ""),
                        )
                        return
                    fix_count += 1
                    jobs.update_job(
                        job_id,
                        phase="fixing_ci",
                        status="fixing_ci",
                        ci_fix_count=fix_count,
                    )
                    _post(channel_id, thread_ts, prog.msg_ci_red())
                    logs = await asyncio.to_thread(cpr.failed_run_logs, cwd=worktree_path)
                    await _run_agent(job, comments=comments, ci_logs=logs)
                    try:
                        await asyncio.to_thread(cpr.push_branch, cwd=worktree_path, branch=branch)
                    except Exception:
                        log.exception("push after CI fix failed")
                    continue

                if last_ci.get("status") and last_ci.get("status") != "green":
                    # Safety: never complete as success unless CI green when we had a PR gate.
                    jobs.update_job(job_id, status="needs_help", phase="needs_help")
                    help_msg = prog.msg_needs_help(pr_url=pr_url, attempts=max_fix)
                    await asyncio.to_thread(
                        cqa.notify_done,
                        summary=help_msg + "\n\n" + str(last_ci),
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                        ask_text=ask,
                        pr_number=int(pr_number),
                        pr_url=pr_url,
                        repo=repo,
                        cwd=worktree_path,
                        jira_key=jira_key,
                        user_id=str(job.get("user_id") or ""),
                    )
                    return

            final = (reply or "").strip()
            if pr_url:
                final = (final + f"\n\nPR: {pr_url}").strip()
            if pr_number and last_ci.get("status") == "green":
                final = (prog.msg_done(pr_url) + "\n\n" + final).strip()
            if len(final) > 12000:
                final = final[:11900] + "\n\n_(truncated)_"
            jobs.update_job(job_id, status="completed", phase="completed", result_text=final[:4000])
            await asyncio.to_thread(
                cqa.notify_done,
                summary=final or prog.msg_done(pr_url),
                channel_id=channel_id,
                thread_ts=thread_ts,
                ask_text=ask,
                pr_number=int(pr_number) if pr_number else None,
                pr_url=pr_url,
                repo=repo,
                cwd=worktree_path or None,
                jira_key=jira_key,
                user_id=str(job.get("user_id") or ""),
            )
            if worktree_path:
                await asyncio.to_thread(wt.remove_worktree, worktree_path, repo_cwd=local_cwd)
            return

        # Read-only path
        job["worktree_path"] = local_cwd
        reply = await _run_agent(job)
        reply = (reply or "").strip() or "Tempa had nothing to add."
        if len(reply) > 12000:
            reply = reply[:11900] + "\n\n_(truncated)_"
        jobs.update_job(job_id, status="completed", phase="completed", result_text=reply[:4000])
        _post(channel_id, thread_ts, reply)

    except Exception as exc:
        log.exception("cursor job failed %s", job_id)
        err = str(exc).strip() or type(exc).__name__
        jobs.update_job(job_id, status="failed", phase="failed", error=err[:500])
        _post(channel_id, thread_ts, prog.msg_problem(err))
    finally:
        stop.set()
        try:
            await ticker
        except Exception:
            pass


async def _worker_loop() -> None:
    settings = get_settings()
    while True:
        try:
            max_p = max(1, int(settings.tempa_cursor_max_parallel or 8))
            active = jobs.count_active_jobs()
            # Active includes queued; approximate running slots.
            running = sum(
                1
                for j in jobs.list_jobs(limit=200)
                if j.get("status") in {"running", "waiting_ci", "fixing_ci", "running_tests"}
            )
            slots = max(0, max_p - running)
            claimed = jobs.claim_next_jobs(slots) if slots else []
            for job in claimed:
                asyncio.create_task(_process_job(job), name=f"cursor-job-{job.get('id')}")
        except Exception:
            log.exception("cursor worker loop error")
        await asyncio.sleep(2)


async def start_cursor_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    # Boot recovery
    interrupted = jobs.interrupt_stale_active_jobs()
    for row in interrupted:
        ch = str(row.get("channel_id") or "")
        th = str(row.get("thread_ts") or "")
        if ch and th:
            _post(ch, th, prog.msg_interrupted())
    try:
        wt.cleanup_orphan_worktrees()
    except Exception:
        log.exception("worktree cleanup failed")
    _worker_task = asyncio.create_task(_worker_loop(), name="tempa-cursor-worker")
    log.info("Tempa Cursor worker started")


async def stop_cursor_worker() -> None:
    global _worker_task
    interrupted = jobs.interrupt_stale_active_jobs()
    for row in interrupted:
        ch = str(row.get("channel_id") or "")
        th = str(row.get("thread_ts") or "")
        if ch and th:
            try:
                _post(ch, th, prog.msg_interrupted())
            except Exception:
                pass
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    _worker_task = None


def enqueue_from_slack(
    *,
    text: str,
    context: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Validate + enqueue. Returns {job_id, queued_position?} or {error}."""
    if not cursor_configured():
        return {"error": "CURSOR_API_KEY is not configured on Tempa."}
    channel_id = str(context.get("slack_channel_id") or context.get("channel_id") or "")
    thread_ts = str(context.get("slack_thread_ts") or context.get("thread_ts") or "")
    user_id = str(context.get("slack_user_id") or context.get("user_id") or "")
    local_cwd = str(cfg.get("local_cwd") or "").strip()
    settings = get_settings()

    write = cpr.is_write_intent(text) or bool(cpr.parse_pr_url(text))
    if write and local_cwd:
        from pathlib import Path
        import os

        if not Path(local_cwd).is_dir():
            return {"error": f"local repo path is not available (`{local_cwd}`)."}
        if not os.access(local_cwd, os.W_OK):
            return {"error": "repo mount is read-only — fix the Tempa Docker volume (need rw)."}
        if not wt.git_available():
            return {"error": "git is not available inside Tempa — cannot run write/QA jobs."}
        if not cpr.gh_available():
            return {"error": "gh CLI is not available inside Tempa — cannot open/check PRs."}

    max_p = max(1, int(settings.tempa_cursor_max_parallel or 8))
    active = jobs.count_active_jobs()
    position = active + 1

    key = jobs.pr_key(
        channel_id=channel_id,
        thread_ts=thread_ts,
        user_id=user_id,
        repo=str(cfg.get("repo") or ""),
    )
    job_id = jobs.enqueue_cursor_job(
        {
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "message_ts": str(context.get("slack_message_ts") or context.get("message_ts") or ""),
            "user_id": user_id,
            "ask_text": text,
            "mode": "write" if write else "read",
            "local_cwd": local_cwd,
            "repo": str(cfg.get("repo") or ""),
            "starting_ref": cfg.get("starting_ref"),
            "base_ref": str(cfg.get("base_ref") or "main"),
            "required_checks": list(cfg.get("required_checks") or ["backend-ci", "frontend-ci", "e2e"]),
            "jira_key": str(cfg.get("jira_key") or "").strip() or None,
            "label": str(cfg.get("label") or ""),
            "pr_key": key,
            "announce_channel": cpr.wants_channel_announce(text),
        }
    )
    out: dict[str, Any] = {"job_id": job_id}
    if position > max_p:
        out["queued_position"] = position - max_p + 1
    return out
