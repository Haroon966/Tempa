"""NL-style digest cron for Tempa (Hermes Phase 3).

Uses APScheduler (already a Tempa dependency). When Hermes coordinator is enabled,
jobs can call the Hermes path; otherwise the tools orchestrator.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_scheduler: Any = None


def _cron_store() -> Path:
    from tempa.settings import get_settings

    path = get_settings().tempa_data_dir / "hermes" / "cron.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def list_cron_jobs() -> list[dict[str, Any]]:
    path = _cron_store()
    if not path.exists():
        return _default_jobs()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        jobs = data.get("jobs") if isinstance(data, dict) else data
        return list(jobs) if isinstance(jobs, list) else _default_jobs()
    except Exception:
        return _default_jobs()


def _default_jobs() -> list[dict[str, Any]]:
    return [
        {
            "id": "daily-briefing",
            "enabled": False,
            "hour": 8,
            "minute": 0,
            "prompt": "Summarize today's calendar and urgent inbox items in 5 bullets.",
            "deliver": "slack",
        },
        {
            "id": "weekly-qa-summary",
            "enabled": False,
            "day_of_week": "mon",
            "hour": 9,
            "minute": 0,
            "prompt": "Summarize open QA findings and recent scan status.",
            "deliver": "slack",
        },
        {
            "id": "open-goals-tick",
            "enabled": False,
            "hour": 10,
            "minute": 0,
            "prompt": "__tick_open_goals__",
            "deliver": "slack",
        },
        {
            "id": "self-improve-curator",
            "enabled": True,
            "hour": 3,
            "minute": 15,
            "prompt": "__run_curator__",
            "deliver": "",
        },
    ]


def save_cron_jobs(jobs: list[dict[str, Any]]) -> None:
    _cron_store().write_text(
        json.dumps({"jobs": jobs, "updated_at": datetime.now(timezone.utc).isoformat()}, indent=2),
        encoding="utf-8",
    )


async def run_cron_job(job: dict[str, Any]) -> str:
    prompt = str(job.get("prompt") or "").strip()
    if not prompt:
        return ""
    if prompt == "__tick_open_goals__":
        text = await _tick_open_goals(job)
        if text and str(job.get("deliver") or "") == "slack":
            await _deliver_slack(text, job)
        return text
    if prompt == "__run_curator__":
        from tempa.learning.curator import run_curator

        result = run_curator()
        return json.dumps(result, ensure_ascii=False)

    from tempa.settings import get_settings

    ctx = {"channel": "cron", "hermes_cron": True, "cron_job_id": job.get("id")}
    if get_settings().tempa_coordinator == "hermes":
        from tempa.hermes.coordinator import run_hermes_coordinator

        result = await run_hermes_coordinator(prompt, ctx)
    else:
        from tempa.orchestrator.agent import run_orchestrator

        result = await run_orchestrator(prompt, ctx)
    text = str(result.get("response") or "").strip()
    deliver = str(job.get("deliver") or "")
    if text and deliver == "slack":
        await _deliver_slack(text, job)
    elif text and deliver == "email":
        await _deliver_email(text, job)
    return text


async def _tick_open_goals(job: dict[str, Any]) -> str:
    from tempa.hermes.goals import list_goals, update_goal

    opens = list_goals(status="open")
    if not opens:
        return "No open goals."
    parts: list[str] = []
    for goal in opens[:5]:
        update_goal(str(goal["id"]), tick=True)
        prompt = str(goal.get("prompt") or goal.get("title") or "")
        # Avoid nested Slack spam — collect and deliver once.
        sub = {
            "id": f"goal-{goal.get('id')}",
            "prompt": f"Standing goal progress check: {prompt}",
            "deliver": "",
        }
        text = await run_cron_job(sub)
        if text:
            parts.append(f"*{goal.get('title')}*\n{text}")
    return "\n\n".join(parts) or "Open goals ticked."


async def _deliver_slack(text: str, job: dict[str, Any]) -> None:
    from tempa.settings import get_settings

    channel = str(job.get("slack_channel_id") or get_settings().slack_owner_user_id or "").strip()
    if not channel:
        logger.info("cron %s: no slack deliver target", job.get("id"))
        return
    try:
        from tempa.channels.slack.outbound import send_slack_message_sync

        send_slack_message_sync(channel, text[:3500], source_channel="hermes_cron")
    except Exception:
        logger.exception("cron slack deliver failed")


async def _deliver_email(text: str, job: dict[str, Any]) -> None:
    logger.info("cron email deliver skipped (use pending approval path): %s", job.get("id"))


def start_hermes_cron() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning("APScheduler not available — Hermes cron disabled")
        return

    jobs = list_cron_jobs()
    if not any(j.get("enabled") for j in jobs):
        logger.info("Hermes cron: no enabled jobs")
        return

    sched = AsyncIOScheduler()
    for job in jobs:
        if not job.get("enabled"):
            continue
        trigger_kwargs: dict[str, Any] = {
            "hour": int(job.get("hour") or 8),
            "minute": int(job.get("minute") or 0),
        }
        if job.get("day_of_week") is not None:
            trigger_kwargs["day_of_week"] = job["day_of_week"]
        jid = str(job.get("id") or "job")

        async def _tick(j: dict[str, Any] = job) -> None:
            try:
                await run_cron_job(j)
            except Exception:
                logger.exception("Hermes cron job failed: %s", j.get("id"))

        sched.add_job(_tick, CronTrigger(**trigger_kwargs), id=f"hermes-{jid}", replace_existing=True)
        logger.info("Hermes cron scheduled: %s", jid)

    sched.start()
    _scheduler = sched


def stop_hermes_cron() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        pass
    _scheduler = None
