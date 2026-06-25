from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.channels.whatsapp.outbound import send_whatsapp_message
from tempa.channels.whatsapp.reply import load_default_whatsapp_number
from tempa.core.events import event_bus
from tempa.core.runtime import get_main_loop, schedule_coro
from tempa.meet.archive import (
    generate_minutes_from_transcript,
    index_meeting_to_rag,
    save_meeting_archive,
    write_meeting_artifacts,
)
from tempa.meet.audio_convert import resolve_audio_path
from tempa.meet.config import AudioConfig, JoinConfig, SttConfig, WorkerConfig
from tempa.meet.consent import has_recording_consent
from tempa.meet.followups import create_followup_pending_actions, generate_followup_drafts
from tempa.meet.job_store import (
    enqueue_meet_job,
    get_all_job_statuses,
    update_job_status,
)
from tempa.meet.notes import live_notes_loop
from tempa.meet.stt.factory import create_stt_adapter
from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_active_jobs: dict[str, asyncio.Task] = {}
_job_status: dict[str, dict[str, Any]] = {}
_job_meta: dict[str, dict[str, Any]] = {}


def _delegate_to_worker() -> bool:
    return os.environ.get("TEMPA_MEET_DELEGATE_TO_WORKER", "").lower() in ("1", "true", "yes")


def build_worker_config(
    meet_url: str,
    meeting_id: str | None = None,
    *,
    duration_seconds: int = 3600,
    calendar_event_id: str | None = None,
    calendar_event_start: str | None = None,
    calendar_event_end: str | None = None,
    attendee_emails: list[str] | None = None,
    started_at: str | None = None,
) -> WorkerConfig:
    settings = get_settings()
    mid = meeting_id or str(uuid.uuid4())
    display = os.environ.get("DISPLAY", "").strip()
    return WorkerConfig(
        meeting_id=mid,
        meet_url=meet_url,
        output_dir=str(settings.meetings_dir),
        duration_seconds=duration_seconds,
        audio=AudioConfig(debug=True),
        stt=SttConfig(provider="groq", extra={"chunk_seconds": 15.0, "language": "en"}),
        join=JoinConfig(
            headless=not bool(display),
            storage_state_path=str(settings.google_storage_state_path),
            bot_name="Tempa",
            disable_mic=True,
            disable_camera=True,
        ),
        calendar_event_id=calendar_event_id,
        calendar_event_start=calendar_event_start,
        calendar_event_end=calendar_event_end,
        attendee_emails=attendee_emails or [],
        started_at=started_at or datetime.now(timezone.utc).isoformat(),
    )


def _parse_transcript_jsonl(path: Path) -> tuple[str, list[dict[str, Any]]]:
    segments: list[dict[str, Any]] = []
    lines: list[str] = []
    if not path.exists():
        return "", segments
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if row.get("type") == "segment" and row.get("text"):
            speaker = row.get("speaker") or "Unknown"
            lines.append(f"{speaker}: {row['text']}")
            segments.append(row)
    return "\n".join(lines), segments


def _format_whatsapp_summary(title: str, minutes: dict[str, Any]) -> str:
    summary = minutes.get("tldr") or minutes.get("summary") or "Meeting completed."
    lines = [f"*{title}* ended.", "", summary]
    action_items = minutes.get("action_items") or []
    if action_items:
        lines.append("")
        lines.append("*Action items:*")
        for item in action_items[:3]:
            if isinstance(item, dict):
                owner = item.get("owner") or "Unassigned"
                task = item.get("task") or ""
                lines.append(f"• {owner}: {task}")
            else:
                lines.append(f"• {item}")
    lines.append("")
    lines.append("Full minutes in Tempa dashboard.")
    return "\n".join(lines)[:3500]


async def _finalize_meeting(
    config: WorkerConfig,
    *,
    title: str,
    transcript_path: Path | None,
    audio_path: Path | None,
    live_notes_path: Path | None,
    notify_number: str | None,
) -> dict[str, Any]:
    meeting_id = config.meeting_id
    meet_url = config.meet_url
    transcript_text, segments = _parse_transcript_jsonl(transcript_path) if transcript_path else ("", [])
    if live_notes_path and live_notes_path.exists():
        live_notes = live_notes_path.read_text(encoding="utf-8")
        if live_notes:
            transcript_text = f"{transcript_text}\n\n--- Live Notes ---\n{live_notes}"

    minutes: dict[str, Any] = {}
    minutes_status = "none"
    if transcript_text.strip():
        try:
            minutes = await generate_minutes_from_transcript(transcript_text, source_name="meeting.jsonl")
            minutes_status = "complete"
        except Exception:
            logger.exception("Minutes generation failed for %s", meeting_id)
            minutes_status = "partial"

    participants = sorted({s.get("speaker") for s in segments if s.get("speaker")})
    wav_path: Path | None = None
    if audio_path and audio_path.exists():
        meeting_dir = audio_path.parent.parent if audio_path.parent.name == "audio" else audio_path.parent
        wav_path = resolve_audio_path(meeting_dir, meeting_id)
    ended_at = datetime.now(timezone.utc).isoformat()
    started_at = config.started_at or ended_at

    followups: list[dict[str, Any]] = []
    if minutes:
        try:
            followups = await generate_followup_drafts(
                minutes,
                title=title,
                attendee_emails=config.attendee_emails,
                transcript_excerpt=transcript_text[-8000:],
            )
        except Exception:
            logger.exception("Follow-up draft generation failed for %s", meeting_id)

    record: dict[str, Any] = {
        "id": meeting_id,
        "title": title or f"Meeting {meeting_id[:8]}",
        "meet_link": meet_url,
        "started_at": started_at,
        "ended_at": ended_at,
        "participants": participants,
        "attendee_emails": config.attendee_emails,
        "calendar_event_id": config.calendar_event_id,
        "calendar_event_start": config.calendar_event_start,
        "audio_path": str(wav_path or audio_path or ""),
        "transcript_path": str(transcript_path) if transcript_path else "",
        "minutes": minutes,
        "minutes_status": minutes_status,
        "followups": followups,
    }

    safe_id = meeting_id.replace("/", "_").replace("\\", "_")
    meeting_dir = Path(config.output_dir) / safe_id
    write_meeting_artifacts(meeting_dir, record, followups)

    await save_meeting_archive(record)
    if transcript_text.strip():
        await index_meeting_to_rag(record, transcript_text)

    pending_ids = create_followup_pending_actions(meeting_id, followups, title=title)

    settings = get_settings()
    if notify_number and settings.meet_auto_send_summary_whatsapp:
        msg = _format_whatsapp_summary(record["title"], minutes)
        if record.get("meet_link"):
            msg += f"\n\nLink: {record['meet_link']}"
        await send_whatsapp_message(notify_number, msg, source_channel="whatsapp_auto_reply")

    await event_bus.publish_json(
        "meet",
        "completed",
        {"meeting_id": meeting_id, "pending_action_ids": pending_ids},
    )
    return record


def _set_status(meeting_id: str, **fields: Any) -> None:
    _job_status[meeting_id] = {**_job_status.get(meeting_id, {}), **fields}
    update_job_status(meeting_id, **fields)


async def _run_meeting_job(
    config: WorkerConfig,
    *,
    title: str = "",
    notify_number: str | None = None,
) -> None:
    safe_id = config.meeting_id.replace("/", "_").replace("\\", "_")
    meeting_dir = Path(config.output_dir) / safe_id
    transcript_path = meeting_dir / "transcripts" / f"{safe_id}.jsonl"
    notes_path = meeting_dir / "live_notes.md"
    suggestions_path = meeting_dir / "suggestions.jsonl"
    audio_glob = list((meeting_dir / "audio").glob("*.pcm")) if (meeting_dir / "audio").exists() else []

    stop_tasks = asyncio.Event()
    notes_task = asyncio.create_task(live_notes_loop(transcript_path, notes_path, stop_tasks))

    copilot_task: asyncio.Task | None = None
    try:
        from tempa.meet.copilot import copilot_loop

        copilot_task = asyncio.create_task(
            copilot_loop(
                config.meeting_id,
                transcript_path,
                notes_path,
                suggestions_path,
                stop_tasks,
                title=title,
            )
        )
    except Exception:
        logger.debug("Copilot loop not started", exc_info=True)

    _set_status(config.meeting_id, status="running", meet_url=config.meet_url, title=title)
    try:
        stt = create_stt_adapter("groq")
        await run_meeting_worker_with_session(config, stt_adapter=stt, title=title)
        _set_status(config.meeting_id, status="finalizing")
        await _finalize_meeting(
            config,
            title=title,
            transcript_path=transcript_path if transcript_path.exists() else None,
            audio_path=audio_glob[0] if audio_glob else None,
            notes_path=notes_path,
            notify_number=notify_number or load_default_whatsapp_number() or None,
        )
        _set_status(config.meeting_id, status="completed")
    except Exception as exc:
        logger.exception("Meeting job failed: %s", config.meeting_id)
        _set_status(config.meeting_id, status="failed", error=str(exc))
        try:
            from tempa.channels.whatsapp.action_state import record_action

            record_action(
                "meet",
                {
                    "status": "failed",
                    "meeting_id": config.meeting_id,
                    "meet_url": config.meet_url,
                    "error": str(exc),
                },
            )
        except Exception:
            pass
        await event_bus.publish_json("meet", "failed", str(exc)[:120])
    finally:
        stop_tasks.set()
        notes_task.cancel()
        if copilot_task:
            copilot_task.cancel()
        try:
            from tempa.meet.session_registry import unregister_session

            unregister_session(config.meeting_id)
        except Exception:
            pass
        _active_jobs.pop(config.meeting_id, None)
        _job_meta.pop(config.meeting_id, None)


async def run_meeting_worker_with_session(
    config: WorkerConfig,
    *,
    stt_adapter: Any = None,
    title: str = "",
) -> None:
    """Run meeting worker and register Playwright page for live chat/copilot."""
    from tempa.meet.joiner import join_meet, wait_for_admission
    from tempa.meet.lifecycle import MeetingEndTracker, check_meeting_ended
    from tempa.meet.pipeline import setup_pipeline
    from tempa.meet.recording_ui import show_recording_notice
    from tempa.meet.session_registry import register_session, unregister_session
    from tempa.meet.storage import LocalStorageAdapter
    import time

    if stt_adapter is None:
        stt_adapter = create_stt_adapter("groq")

    storage_adapter = LocalStorageAdapter()
    safe_id = config.meeting_id.replace("/", "_").replace("\\", "_")
    meeting_base_dir = os.path.join(config.output_dir, safe_id)
    screenshot_dir = config.join.screenshot_dir or os.path.join(meeting_base_dir, "screenshots")

    session = await join_meet(
        config.meet_url,
        headless=config.join.headless,
        storage_state_path=config.join.storage_state_path,
        bot_name=config.join.bot_name,
        disable_mic=config.join.disable_mic,
        disable_camera=config.join.disable_camera,
        join_timeout_ms=config.join.join_timeout_ms,
        screenshot_dir=screenshot_dir,
        storage_adapter=storage_adapter,
    )
    admitted = await wait_for_admission(session.page, timeout_s=180.0)
    if not admitted:
        await session.close()
        raise RuntimeError("Timed out waiting for Meet admission")

    register_session(config.meeting_id, session.page, meet_url=config.meet_url, title=title)
    await show_recording_notice(session.page)
    pipeline = await setup_pipeline(
        session,
        meeting_id=config.meeting_id,
        audio=config.audio,
        stt=config.stt,
        output_dir=config.output_dir,
        storage_adapter=storage_adapter,
        stt_adapter=stt_adapter,
    )

    settings = get_settings()
    end_tracker = MeetingEndTracker(alone_grace_seconds=float(settings.meet_alone_grace_seconds))
    start_time = time.time()
    try:
        while True:
            await asyncio.sleep(30)
            if await check_meeting_ended(session.page, tracker=end_tracker):
                break
            if time.time() - start_time >= config.duration_seconds:
                break
    finally:
        await pipeline.close()
        unregister_session(config.meeting_id)
        await session.close()


def run_meeting_job_sync(
    config: WorkerConfig,
    *,
    title: str = "",
    notify_number: str | None = None,
) -> None:
    """Run a meeting job in a worker process (fresh event loop)."""
    asyncio.run(_run_meeting_job(config, title=title, notify_number=notify_number))


async def schedule_meeting_join_async(
    meet_url: str,
    *,
    title: str = "",
    meeting_id: str | None = None,
    notify_number: str | None = None,
    calendar_event_id: str | None = None,
    calendar_event_start: str | None = None,
    calendar_event_end: str | None = None,
    attendee_emails: list[str] | None = None,
    duration_seconds: int = 3600,
) -> str:
    if not has_recording_consent():
        raise RuntimeError("Recording consent not granted. Enable via dashboard, extension, or `tempa setup`.")

    meta = {
        "calendar_event_id": calendar_event_id,
        "calendar_event_start": calendar_event_start,
        "calendar_event_end": calendar_event_end,
        "attendee_emails": attendee_emails or [],
        "duration_seconds": duration_seconds,
    }
    _job_meta[meeting_id or "pending"] = meta

    if _delegate_to_worker():
        mid = enqueue_meet_job(
            meet_url,
            title=title,
            meeting_id=meeting_id,
            notify_number=notify_number,
            extra=meta,
        )
        _job_status[mid] = {"status": "queued", "meet_url": meet_url, "title": title, **meta}
        return mid

    config = build_worker_config(
        meet_url,
        meeting_id,
        duration_seconds=duration_seconds,
        calendar_event_id=calendar_event_id,
        calendar_event_start=calendar_event_start,
        calendar_event_end=calendar_event_end,
        attendee_emails=attendee_emails,
    )
    if config.meeting_id in _active_jobs:
        return config.meeting_id

    _job_meta[config.meeting_id] = meta
    task = asyncio.create_task(
        _run_meeting_job(config, title=title, notify_number=notify_number),
        name=f"meet-{config.meeting_id}",
    )
    _active_jobs[config.meeting_id] = task
    _set_status(config.meeting_id, status="queued", meet_url=meet_url, title=title, **meta)
    return config.meeting_id


def schedule_meeting_join(
    meet_url: str,
    *,
    title: str = "",
    meeting_id: str | None = None,
    notify_number: str | None = None,
    calendar_event_id: str | None = None,
    calendar_event_start: str | None = None,
    calendar_event_end: str | None = None,
    attendee_emails: list[str] | None = None,
    duration_seconds: int = 3600,
) -> str:
    if not has_recording_consent():
        raise RuntimeError("Recording consent not granted. Enable via dashboard, extension, or `tempa setup`.")

    meta = {
        "calendar_event_id": calendar_event_id,
        "calendar_event_start": calendar_event_start,
        "calendar_event_end": calendar_event_end,
        "attendee_emails": attendee_emails or [],
        "duration_seconds": duration_seconds,
    }

    if _delegate_to_worker():
        mid = enqueue_meet_job(
            meet_url,
            title=title,
            meeting_id=meeting_id,
            notify_number=notify_number,
            extra=meta,
        )
        _job_status[mid] = {"status": "queued", "meet_url": meet_url, "title": title, **meta}
        return mid

    config = build_worker_config(
        meet_url,
        meeting_id,
        duration_seconds=duration_seconds,
        calendar_event_id=calendar_event_id,
        calendar_event_start=calendar_event_start,
        calendar_event_end=calendar_event_end,
        attendee_emails=attendee_emails,
    )
    if config.meeting_id in _active_jobs:
        return config.meeting_id

    coro = _run_meeting_job(config, title=title, notify_number=notify_number)
    loop = get_main_loop()
    if loop and loop.is_running():
        task = asyncio.run_coroutine_threadsafe(coro, loop)
        _active_jobs[config.meeting_id] = task  # type: ignore[assignment]
    else:
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(coro, name=f"meet-{config.meeting_id}")
            _active_jobs[config.meeting_id] = task
        except RuntimeError:
            scheduled = schedule_coro(coro)
            if scheduled is None:
                raise RuntimeError("No running event loop to schedule Meet join")
            _active_jobs[config.meeting_id] = scheduled  # type: ignore[assignment]

    _set_status(config.meeting_id, status="queued", meet_url=meet_url, title=title, **meta)
    return config.meeting_id


def get_meeting_jobs() -> dict[str, dict[str, Any]]:
    merged = get_all_job_statuses()
    merged.update(_job_status)
    return merged


def get_active_meeting_ids() -> list[str]:
    jobs = get_meeting_jobs()
    return [mid for mid, row in jobs.items() if row.get("status") in ("queued", "running", "finalizing")]
