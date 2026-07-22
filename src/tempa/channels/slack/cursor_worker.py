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
_job_sem: asyncio.Semaphore | None = None
_repo_locks: dict[str, asyncio.Lock] = {}
_repo_locks_guard = asyncio.Lock()


def _global_job_sem() -> asyncio.Semaphore:
    global _job_sem
    settings = get_settings()
    limit = max(1, int(settings.tempa_cursor_max_parallel or 8))
    if _job_sem is None or getattr(_job_sem, "_tempa_limit", None) != limit:
        _job_sem = asyncio.Semaphore(limit)
        setattr(_job_sem, "_tempa_limit", limit)
    return _job_sem


async def _repo_lock(repo: str) -> asyncio.Lock:
    key = (repo or "").strip().lower() or "_default"
    async with _repo_locks_guard:
        lock = _repo_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _repo_locks[key] = lock
        return lock


async def _process_job_guarded(job: dict[str, Any]) -> None:
    """Respect global concurrency + per-repo write serialization."""
    sem = _global_job_sem()
    async with sem:
        mode = str(job.get("mode") or "read")
        repo = str(job.get("repo") or "")
        if mode == "write" and repo:
            lock = await _repo_lock(repo)
            async with lock:
                await _process_job(job)
        else:
            await _process_job(job)


def _post(channel_id: str, thread_ts: str, text: str) -> None:
    from tempa.channels.slack.outbound import send_slack_message_sync

    try:
        send_slack_message_sync(channel_id, text, thread_ts=thread_ts, source_channel="cursor_job")
    except Exception:
        log.exception("cursor worker slack post failed")


async def _progress_ticker(job_id: str, channel_id: str, thread_ts: str, stop: asyncio.Event) -> None:
    """Heartbeat job store only — do not spam Slack while work runs in the background."""
    settings = get_settings()
    interval = max(30, int(settings.tempa_cursor_progress_interval_sec or 120))
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
        jobs.update_job(job_id, last_progress_at=jobs._now_iso())


def _is_timeout_error(err: str) -> bool:
    lower = (err or "").lower()
    return "timeouterror" in lower or lower == "timeout" or "timed out" in lower


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
    if str(job.get("mode") or "") == "write" and not str(job.get("local_cwd") or "").strip():
        parts.append(
            "Cloud write mode: fix the issues from the request/findings, commit, and open a PR. "
            "Do not ask which issues to fix — address all open findings and the user's ask."
        )
    test_env = os.environ.get("TEMPA_CURSOR_TEST_ENV_FILE", "").strip()
    if test_env:
        parts.append(
            f"Test credentials/context file (use when running tests the user asked for): {test_env}"
        )
    if comments:
        parts.append("PR comments to address:\n" + comments[:6000])
    if ci_logs:
        parts.append("CI failure logs:\n" + ci_logs[:8000])
    repo = str(job.get("repo") or "").strip()
    if repo and str(job.get("mode") or "") == "write":
        try:
            from tempa.qa.results_reply import format_qa_results_reply

            findings = format_qa_results_reply(repo)
            if findings and "don't see which repo" not in findings.lower():
                parts.append("Known QA findings to fix:\n" + findings[:6000])
        except Exception:
            pass
    parts.append("User request:\n" + str(job.get("ask_text") or ""))
    return "\n\n".join(parts)


async def _run_agent(job: dict[str, Any], *, comments: str = "", ci_logs: str = "") -> str:
    prompt = _build_agent_prompt(job, comments=comments, ci_logs=ci_logs)
    cwd = str(job.get("worktree_path") or job.get("local_cwd") or "")
    # Long-running by design — teammates prefer silence until the fix lands.
    timeout = max(300, int(get_settings().tempa_cursor_job_timeout_sec or 7200))
    auto_pr = str(job.get("mode") or "") == "write" and not cwd
    return await asyncio.wait_for(
        cursor_prompt(
            prompt,
            repo=str(job.get("repo") or ""),
            starting_ref=job.get("starting_ref"),
            local_cwd=cwd,
            auto_create_pr=auto_pr,
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
        required = list(job.get("required_checks") or [])
        base_ref = str(job.get("base_ref") or "main")
        jira_key = str(job.get("jira_key") or "").strip() or None
        repo = str(job.get("repo") or "")

        adopted = cpr.parse_pr_url(ask)
        worktree_path = ""
        branch = ""
        pr_url = ""
        pr_number: int | None = None
        jira_key = cqa.extract_jira_key(ask, jira_key)

        if (mode == "write" or adopted) and not local_cwd:
            # Unmounted GitHub target — Cursor cloud agent fixes + opens the PR.
            if not repo:
                raise RuntimeError("repo required for cloud write jobs")
            jobs.update_job(job_id, phase="running", status="running")
            reply = await _run_agent(job)
            reply = (reply or "").strip() or "Tempa finished the cloud fix pass."
            if len(reply) > 12000:
                reply = reply[:11900] + "\n\n_(truncated)_"
            jobs.update_job(job_id, status="completed", phase="completed", result_text=reply[:4000])
            _post(channel_id, thread_ts, reply)
            return

        if mode == "write" or adopted:
            if not local_cwd:
                raise RuntimeError("local_cwd required for write/QA jobs")
            if not wt.git_available():
                raise RuntimeError("git is not available in the Tempa environment")
            # Host bind-mounts are often a different uid than the container user.
            await asyncio.to_thread(wt.ensure_git_safe_directories, local_cwd, "/repos")
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
                    # Stay quiet — only notify when CI is green / final result is ready.
                except Exception as exc:
                    log.warning("pr create skipped/failed: %s", exc)

            # CI / comments loop — only when required_checks is configured.
            last_ci: dict[str, Any] = {}
            if pr_number and required:
                max_fix = max(1, int(settings.tempa_cursor_ci_fix_max or 3))
                # CI wait can outlive a single agent turn; default 2h quiet background.
                timeout_sec = max(600, int(settings.tempa_cursor_job_timeout_sec or 7200) * 2)
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
                            # Escalate owners only — don't worry the requester about wait time.
                            await asyncio.to_thread(
                                cqa.notify_done,
                                summary=(
                                    f"CI still pending on <{pr_url}> after {timeout_sec // 60}m — "
                                    "needs a human look.\n\n" + str(summary)
                                ),
                                channel_id=channel_id,
                                thread_ts=thread_ts,
                                ask_text=ask,
                                pr_number=int(pr_number),
                                pr_url=pr_url,
                                repo=repo,
                                cwd=worktree_path,
                                jira_key=jira_key,
                                user_id=str(job.get("user_id") or ""),
                                escalate_only=True,
                            )
                            return
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
                    # Quiet CI fix cycle — no mid-flight Slack spam.
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

        # Read-only path — still mark host mounts safe so agent `git` calls work.
        if local_cwd:
            await asyncio.to_thread(wt.ensure_git_safe_directories, local_cwd, "/repos")
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
        # One auto-heal retry for Docker git ownership (today's teammate-facing failure).
        if (
            local_cwd
            and not job.get("_safe_git_retried")
            and ("dubious ownership" in err.lower() or "safe.directory" in err.lower())
        ):
            try:
                await asyncio.to_thread(wt.ensure_git_safe_directories, local_cwd, "/repos")
                jobs.update_job(job_id, status="running", phase="running", error=None)
                await _process_job({**job, "_safe_git_retried": True})
                return
            except Exception:
                log.exception("safe.directory retry failed %s", job_id)
        # Timeout: keep working once more in background — never tell the user "too long".
        if _is_timeout_error(err) and not job.get("_timeout_retried"):
            log.warning("cursor job %s timed out — silent background retry", job_id)
            jobs.update_job(job_id, status="running", phase="running", error=None)
            await _process_job({**job, "_timeout_retried": True})
            return
        if _is_timeout_error(err):
            jobs.update_job(job_id, status="needs_help", phase="needs_help", error=err[:500])
            await asyncio.to_thread(
                cqa.notify_done,
                summary=(
                    f"Background Cursor job timed out after retry for ask:\n"
                    f"{(ask or '')[:400]}\n\n(internal: {err[:200]})"
                ),
                channel_id=channel_id,
                thread_ts=thread_ts,
                ask_text=ask,
                pr_number=None,
                pr_url="",
                repo=str(job.get("repo") or ""),
                cwd=local_cwd or None,
                jira_key=str(job.get("jira_key") or "") or None,
                user_id=str(job.get("user_id") or ""),
                escalate_only=True,
            )
            return
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
                asyncio.create_task(
                    _process_job_guarded(job),
                    name=f"cursor-job-{job.get('id')}",
                )
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
        wt.ensure_git_safe_directories("/repos", "/repos/compliancetracker")
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
    repo = str(cfg.get("repo") or "").strip()
    # Cloud write when we have a GitHub repo but no mount (Cursor opens the PR).
    if write and not local_cwd and not repo:
        return {"error": "need a GitHub repo (or a mounted checkout) to raise a PR."}
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

    # Enrich short follow-ups with thread context so Cursor sees prior findings.
    ask_text = text
    try:
        from tempa.channels.slack.cursor_threads import thread_coding_context_blob

        blob = thread_coding_context_blob(context)
        if blob and blob.strip() and blob.strip() not in text:
            ask_text = f"{text}\n\nSlack thread context:\n{blob.strip()[:6000]}"
    except Exception:
        pass

    key = jobs.pr_key(
        channel_id=channel_id,
        thread_ts=thread_ts,
        user_id=user_id,
        repo=repo,
    )
    job_id = jobs.enqueue_cursor_job(
        {
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "message_ts": str(context.get("slack_message_ts") or context.get("message_ts") or ""),
            "user_id": user_id,
            "ask_text": ask_text,
            "mode": "write" if write else "read",
            "local_cwd": local_cwd,
            "repo": repo,
            "starting_ref": cfg.get("starting_ref"),
            "base_ref": str(cfg.get("base_ref") or "main"),
            "required_checks": list(cfg.get("required_checks") or []),
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
