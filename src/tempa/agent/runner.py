"""Interactive Tempa turns via Cursor Agent.create/resume + live activity."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from tempa.agent.activity import merge_steps, step_from_sdk_message
from tempa.agent.context import build_turn_prompt
from tempa.agent.prompts import system_preamble
from tempa.agent.sessions import clear_session, get_session, save_session
from tempa.agent.tools import build_custom_tools
from tempa.qa.cursor import cursor_configured
from tempa.settings import get_settings

logger = logging.getLogger(__name__)

ActivityCallback = Callable[[list[str], bool], Awaitable[None] | None]

_CANCEL_RE = re.compile(r"^\s*(stop|cancel|abort|never\s*mind|nvm)\b", re.I)

# One active run per thread
_active_lock = threading.Lock()
_active_runs: dict[str, Any] = {}  # thread_key -> Run | "pending"
_cancelled_keys: set[str] = set()
_thread_locks: dict[str, asyncio.Lock] = {}
_thread_locks_guard = threading.Lock()


def tempa_agent_available() -> bool:
    return cursor_configured()


def is_cancel_request(text: str) -> bool:
    return bool(_CANCEL_RE.match((text or "").strip()))


def agent_home_cwd() -> str:
    settings = get_settings()
    home = Path(getattr(settings, "tempa_agent_home", "") or "").expanduser()
    if str(home).strip() and home.is_dir():
        return str(home.resolve())
    return str(settings.project_root)


def resolve_workspace(
    *,
    text: str,
    channel_id: str = "",
    thread_ts: str = "",
) -> tuple[str, str]:
    """Return (local_cwd, repo). Use a repo mount only for coding/pin/Rumi — else agent-home."""
    try:
        from tempa.channels.slack.cursor_threads import (
            is_cursor_thread,
            resolve_cursor_job_cfg,
            rumi_agent_job_cfg,
        )
        from tempa.rumi.classify import classify_rumi

        if classify_rumi(text) == "agent":
            cfg = rumi_agent_job_cfg()
            cwd = str(cfg.get("local_cwd") or "").strip()
            if cwd:
                return cwd, str(cfg.get("repo") or "").strip()
            return agent_home_cwd(), ""

        pinned = bool(channel_id and thread_ts and is_cursor_thread(channel_id, thread_ts))
        coding = False
        try:
            from tempa.orchestrator.routing import is_coding_work_request

            coding = is_coding_work_request(text, {"channel_id": channel_id, "thread_ts": thread_ts})
        except Exception:
            coding = False

        if not pinned and not coding:
            return agent_home_cwd(), ""

        cfg = resolve_cursor_job_cfg(text, channel_id=channel_id, thread_ts=thread_ts)
        if cfg:
            cwd = str(cfg.get("local_cwd") or "").strip()
            repo = str(cfg.get("repo") or "").strip()
            if cwd:
                return cwd, repo
            return agent_home_cwd(), repo
    except Exception:
        logger.debug("workspace resolve failed", exc_info=True)
    return agent_home_cwd(), ""


def _thread_key(channel: str, thread_id: str) -> str:
    return f"{channel}|{thread_id}"


def thread_has_active_run(*, channel: str, thread_id: str) -> bool:
    key = _thread_key(channel, thread_id)
    with _active_lock:
        return key in _active_runs


def claim_thread_lock(*, channel: str, thread_id: str) -> asyncio.Lock:
    """Share the per-thread asyncio lock with ingress (status before run)."""
    return _asyncio_lock_for(_thread_key(channel, thread_id))


def _asyncio_lock_for(key: str) -> asyncio.Lock:
    with _thread_locks_guard:
        lock = _thread_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _thread_locks[key] = lock
        return lock


def cancel_thread_run(*, channel: str, thread_id: str) -> bool:
    key = _thread_key(channel, thread_id)
    with _active_lock:
        _cancelled_keys.add(key)
        run = _active_runs.pop(key, None)
    if run is None or run == "pending":
        # Pending: flag stays set so begin/_run_locked/_run_agent_sync abort.
        return True
    try:
        if hasattr(run, "supports") and run.supports("cancel"):
            run.cancel()
            return True
        if hasattr(run, "cancel"):
            run.cancel()
            return True
    except Exception:
        logger.warning("cancel failed for %s", key, exc_info=True)
    return True


def begin_thread_run(*, channel: str, thread_id: str) -> bool:
    """Register pending before status posts. False if already cancelled."""
    key = _thread_key(channel, thread_id)
    with _active_lock:
        if key in _cancelled_keys:
            _cancelled_keys.discard(key)
            return False
        _active_runs[key] = "pending"
    return True


class _RunCancelled(Exception):
    """Interactive run aborted after stop/cancel."""


def _extract_result_text(result: Any) -> str:
    text = str(getattr(result, "result", None) or "").strip()
    if text:
        return text
    # Some SDK versions put text on the run conversation
    return ""


def _run_agent_sync(
    *,
    prompt: str,
    agent_id: str | None,
    local_cwd: str,
    user_id: str,
    thread_key: str,
    on_step: Callable[[list[str]], None] | None,
) -> tuple[str, str]:
    """Create or resume agent, stream steps, return (reply_text, agent_id)."""
    from cursor_sdk import Agent, AgentOptions, LocalAgentOptions

    settings = get_settings()
    api_key = settings.cursor_api_key.strip()
    model = settings.tempa_qa_cursor_model.strip() or "composer-2.5"
    tools = build_custom_tools(default_user_id=user_id)
    local = LocalAgentOptions(cwd=local_cwd, custom_tools=tools)
    full_prompt = f"{system_preamble()}\n\n{prompt}"

    options = AgentOptions(
        api_key=api_key,
        model=model,
        local=local,
    )

    agent_cm: Any
    if agent_id:
        agent_cm = Agent.resume(agent_id, options)
    else:
        agent_cm = Agent.create(options)

    steps: list[str] = []
    with agent_cm as agent:
        new_id = str(getattr(agent, "agent_id", None) or getattr(agent, "agentId", None) or agent_id or "")
        with _active_lock:
            if thread_key in _cancelled_keys:
                _cancelled_keys.discard(thread_key)
                raise _RunCancelled()
        run = agent.send(full_prompt)
        with _active_lock:
            if thread_key in _cancelled_keys:
                _cancelled_keys.discard(thread_key)
                try:
                    if hasattr(run, "cancel"):
                        run.cancel()
                except Exception:
                    logger.debug("cancel after send failed", exc_info=True)
                raise _RunCancelled()
            _active_runs[thread_key] = run
        try:
            try:
                for msg in run.messages():
                    with _active_lock:
                        if thread_key in _cancelled_keys:
                            _cancelled_keys.discard(thread_key)
                            try:
                                if hasattr(run, "cancel"):
                                    run.cancel()
                            except Exception:
                                pass
                            raise _RunCancelled()
                    step = step_from_sdk_message(msg)
                    if step:
                        steps = merge_steps(steps, step)
                        if on_step:
                            on_step(steps)
            except _RunCancelled:
                raise
            except Exception:
                logger.debug("stream messages failed; waiting for result", exc_info=True)
            result = run.wait()
            status = str(getattr(result, "status", "") or "")
            if status == "error":
                raise RuntimeError(f"Tempa agent run failed (id={getattr(result, 'id', '')})")
            text = _extract_result_text(result)
            if not text and hasattr(run, "text"):
                try:
                    text = str(run.text() or "").strip()
                except Exception:
                    pass
            if not text:
                # Last assistant step as fallback
                text = next((s for s in reversed(steps) if s and not s.endswith("…")), "") or (
                    "Done — see the activity above for details."
                )
            return text, new_id or agent_id or ""
        finally:
            with _active_lock:
                cur = _active_runs.get(thread_key)
                if cur is run or cur == "pending":
                    _active_runs.pop(thread_key, None)


async def handle_interactive_turn(
    *,
    user_message: str,
    channel: str,
    thread_id: str,
    user_id: str = "",
    channel_kind: str = "slack",
    extra_context: dict[str, Any] | None = None,
    on_activity: ActivityCallback | None = None,
    already_locked: bool = False,
) -> dict[str, Any]:
    """Run one interactive Tempa turn. Sole interactive brain when Cursor is configured."""
    if not tempa_agent_available():
        from tempa.channels.slack.cursor_progress import msg_unavailable

        return {"ok": False, "reply": msg_unavailable(), "error": "agent_unavailable"}

    key = _thread_key(channel, thread_id)

    async def _run_locked() -> dict[str, Any]:
        # Pending may already be set by ingress (before status). Never clear
        # cancel flags on enter — that wiped stop requests during setup.
        with _active_lock:
            if key in _cancelled_keys:
                _cancelled_keys.discard(key)
                _active_runs.pop(key, None)
                from tempa.channels.slack.cursor_progress import msg_stopped

                return {"ok": False, "reply": msg_stopped(), "error": "cancelled"}
            _active_runs.setdefault(key, "pending")

        try:
            cwd, repo = resolve_workspace(
                text=user_message,
                channel_id=channel if channel_kind == "slack" else "",
                thread_ts=thread_id if channel_kind == "slack" else "",
            )
            with _active_lock:
                if key in _cancelled_keys:
                    _cancelled_keys.discard(key)
                    from tempa.channels.slack.cursor_progress import msg_stopped

                    return {"ok": False, "reply": msg_stopped(), "error": "cancelled"}

            ctx = dict(extra_context or {})
            if repo:
                ctx.setdefault("repo", repo)
            if cwd:
                ctx.setdefault("local_cwd", cwd)

            # Claim ownership immediately so channel follow-ups without @mention work mid-run.
            prior = get_session(channel=channel, thread_id=thread_id)
            save_session(
                channel=channel,
                thread_id=thread_id,
                agent_id=str((prior or {}).get("agent_id") or "pending"),
                local_cwd=cwd,
                repo=repo,
                user_id=user_id,
            )

            prompt = build_turn_prompt(
                user_message=user_message,
                channel=channel,
                thread_id=thread_id,
                user_id=user_id,
                channel_kind=channel_kind,
                extra_context=ctx,
            )

            sess = get_session(channel=channel, thread_id=thread_id)
            agent_id = str((sess or {}).get("agent_id") or "").strip() or None
            if agent_id == "pending":
                agent_id = None
            # If cwd changed vs prior session, start fresh (wrong workspace is worse).
            if prior and str(prior.get("local_cwd") or "") and str(prior.get("local_cwd")) != cwd:
                agent_id = None

            loop = asyncio.get_running_loop()
            last_posted: list[str] = []

            def _on_step(steps: list[str]) -> None:
                nonlocal last_posted
                if steps == last_posted:
                    return
                last_posted = list(steps)
                if on_activity is None:
                    return
                fut = asyncio.run_coroutine_threadsafe(
                    _maybe_await_activity(on_activity, steps, False), loop
                )
                try:
                    fut.result(timeout=15)
                except Exception:
                    logger.debug("activity callback failed", exc_info=True)

            try:
                reply, new_agent_id = await asyncio.to_thread(
                    _run_agent_sync,
                    prompt=prompt,
                    agent_id=agent_id,
                    local_cwd=cwd,
                    user_id=user_id,
                    thread_key=key,
                    on_step=_on_step,
                )
            except _RunCancelled:
                from tempa.channels.slack.cursor_progress import msg_stopped

                return {"ok": False, "reply": msg_stopped(), "error": "cancelled"}
            except Exception as exc:
                logger.exception("interactive Tempa turn failed")
                from tempa.channels.slack.cursor_progress import msg_problem

                return {"ok": False, "reply": msg_problem(exc), "error": "run_failed"}

            with _active_lock:
                if key in _cancelled_keys:
                    _cancelled_keys.discard(key)
                    from tempa.channels.slack.cursor_progress import msg_stopped

                    return {"ok": False, "reply": msg_stopped(), "error": "cancelled"}

            if new_agent_id:
                save_session(
                    channel=channel,
                    thread_id=thread_id,
                    agent_id=new_agent_id,
                    local_cwd=cwd,
                    repo=repo,
                    user_id=user_id,
                )

            if on_activity and last_posted:
                await _maybe_await_activity(on_activity, last_posted, True)

            try:
                from tempa.learning.loop import schedule_after_turn

                schedule_after_turn(
                    user_message,
                    success=True,
                    response=reply,
                    context={
                        "user_id": user_id,
                        "channel": channel,
                        "thread_id": thread_id,
                        "channel_kind": channel_kind,
                    },
                )
            except Exception:
                logger.debug("schedule_after_turn failed", exc_info=True)

            return {
                "ok": True,
                "reply": reply,
                "agent_id": new_agent_id,
                "local_cwd": cwd,
                "repo": repo,
            }
        finally:
            with _active_lock:
                _active_runs.pop(key, None)

    if already_locked:
        return await _run_locked()
    lock = _asyncio_lock_for(key)
    async with lock:
        return await _run_locked()



async def _maybe_await_activity(
    cb: ActivityCallback,
    steps: list[str],
    done: bool,
) -> None:
    result = cb(steps, done)
    if asyncio.iscoroutine(result):
        await result
