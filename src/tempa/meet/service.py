from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.channels.whatsapp.reply import load_default_whatsapp_number
from tempa.core.events import event_bus
from tempa.core.runtime import get_main_loop, schedule_coro
from tempa.meet.archive import (
    _parse_transcript_jsonl,
    generate_minutes_from_transcript,
    index_meeting_to_rag,
    save_meeting_archive,
    write_meeting_artifacts,
)
from tempa.meet.audio_convert import resolve_audio_path
from tempa.meet.config import AudioConfig, JoinConfig, SttConfig, VideoConfig, WorkerConfig
from tempa.meet.consent import has_recording_consent
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
    organizer_email: str | None = None,
    started_at: str | None = None,
    av_test_youtube_url: str | None = None,
    display: str | None = None,
    pulse_sink: str | None = None,
    pulse_monitor_source: str | None = None,
) -> WorkerConfig:
    settings = get_settings()
    mid = meeting_id or str(uuid.uuid4())
    display = (display or os.environ.get("DISPLAY", "")).strip()
    if display and not display.startswith(":"):
        display = f":{display}"
    virtual_cam = settings.resolved_virtual_camera_path()
    if av_test_youtube_url:
        virtual_cam = None
    return WorkerConfig(
        meeting_id=mid,
        meet_url=meet_url,
        output_dir=str(settings.meetings_dir),
        duration_seconds=duration_seconds,
        audio=AudioConfig(debug=True),
        video=VideoConfig(
            record_enabled=settings.meet_record_video,
            width=settings.meet_record_video_width,
            height=settings.meet_record_video_height,
        ),
        stt=SttConfig(provider="groq", extra={"chunk_seconds": 15.0, "language": "en"}),
        join=JoinConfig(
            headless=not bool(display),
            storage_state_path=str(settings.google_storage_state_path),
            bot_name="Tempa",
            disable_mic=True,
            disable_camera=virtual_cam is None,
            virtual_camera_path=str(virtual_cam) if virtual_cam else None,
            display=display or None,
            pulse_sink=pulse_sink,
        ),
        calendar_event_id=calendar_event_id,
        calendar_event_start=calendar_event_start,
        calendar_event_end=calendar_event_end,
        attendee_emails=attendee_emails or [],
        organizer_email=organizer_email,
        started_at=started_at or datetime.now(timezone.utc).isoformat(),
        av_test_youtube_url=av_test_youtube_url,
        pulse_monitor_source=pulse_monitor_source,
    )


def _format_whatsapp_summary(title: str, minutes: dict[str, Any]) -> str:
    from tempa.meet.notify import format_meeting_summary

    return format_meeting_summary(title, minutes, for_slack=False)


def _latest_pcm_path(meeting_dir: Path) -> Path | None:
    audio_dir = meeting_dir / "audio"
    if not audio_dir.exists():
        return None
    pcm_files = sorted(audio_dir.glob("*.pcm"), key=lambda p: p.stat().st_mtime, reverse=True)
    return pcm_files[0] if pcm_files else None


async def _try_finalize_partial_meeting(
    config: WorkerConfig,
    *,
    title: str,
    meeting_dir: Path,
    transcript_path: Path,
    notes_path: Path,
) -> bool:
    """Best-effort archive when a meeting job fails but artifacts exist on disk."""
    from tempa.meet.archive import _parse_transcript_jsonl

    audio_path = _latest_pcm_path(meeting_dir)
    _, segments = _parse_transcript_jsonl(transcript_path)
    has_audio = audio_path is not None and audio_path.exists()
    if not segments and not has_audio:
        return False

    if not segments and has_audio:
        try:
            from tempa.meet.transcribe import transcribe_meeting_audio

            await transcribe_meeting_audio(config.meeting_id)
        except Exception:
            logger.exception("Post-failure audio transcription failed for %s", config.meeting_id)

    try:
        await _finalize_meeting(
            config,
            title=title,
            transcript_path=transcript_path if transcript_path.exists() else None,
            audio_path=audio_path,
            live_notes_path=notes_path if notes_path.exists() else None,
            notify_number=None,
            send_notifications=False,
        )
        return True
    except Exception:
        logger.exception("Post-failure finalize failed for %s", config.meeting_id)
        return False


async def _finalize_meeting(
    config: WorkerConfig,
    *,
    title: str,
    transcript_path: Path | None,
    audio_path: Path | None,
    live_notes_path: Path | None,
    notify_number: str | None,
    send_notifications: bool = True,
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
            minutes = await generate_minutes_from_transcript(transcript_text, source_name="transcript.txt")
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
    # Attendee-wide email/WhatsApp follow-up drafts are disabled — notes go to
    # organizer + owner only via notify_meeting_completed.

    record: dict[str, Any] = {
        "id": meeting_id,
        "title": title or f"Meeting {meeting_id[:8]}",
        "meet_link": meet_url,
        "started_at": started_at,
        "ended_at": ended_at,
        "participants": participants,
        "attendee_emails": config.attendee_emails,
        "organizer_email": config.organizer_email,
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

    import asyncio

    from tempa.meet.media import finalize_meeting_media_files

    await asyncio.to_thread(
        finalize_meeting_media_files,
        meeting_id,
        audio_path_hint=str(audio_path or ""),
    )

    from tempa.settings import get_settings

    yt: dict[str, Any] | None = None
    if get_settings().meet_youtube_upload_enabled:
        from tempa.meet.youtube_upload import maybe_upload_meeting_to_youtube

        yt = await asyncio.to_thread(
            maybe_upload_meeting_to_youtube,
            meeting_id,
            title or f"Meeting {meeting_id[:8]}",
            meet_link=meet_url,
            audio_path_hint=str(audio_path or ""),
        )
        if yt and yt.get("youtube_video_id"):
            record["youtube_video_id"] = yt["youtube_video_id"]
            record["youtube_url"] = yt.get("youtube_url") or f"https://youtu.be/{yt['youtube_video_id']}"

    write_meeting_artifacts(meeting_dir, record, followups)

    await save_meeting_archive(record)

    # Only drop the local copy once the YouTube id is persisted above, so a crash
    # never leaves us with a deleted recording and no link on record.
    if yt and yt.get("confirmed") and record.get("youtube_video_id"):
        from tempa.meet.media import delete_local_meeting_video

        await asyncio.to_thread(delete_local_meeting_video, meeting_id)

    if transcript_text.strip():
        await index_meeting_to_rag(record, transcript_text)

    pending_ids: list[str] = []

    from tempa.meet.notify import notify_meeting_completed

    notes_excerpt = ""
    if live_notes_path and live_notes_path.exists():
        notes_excerpt = live_notes_path.read_text(encoding="utf-8")[:2500]

    if send_notifications:
        await notify_meeting_completed(
            record, minutes, notify_number=notify_number, live_notes_excerpt=notes_excerpt
        )

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
    audio_path = _latest_pcm_path(meeting_dir)

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
            audio_path=audio_path,
            live_notes_path=notes_path,
            notify_number=notify_number or load_default_whatsapp_number() or None,
        )
        _set_status(config.meeting_id, status="completed")
    except Exception as exc:
        logger.exception("Meeting job failed: %s", config.meeting_id)
        repaired = await _try_finalize_partial_meeting(
            config,
            title=title,
            meeting_dir=meeting_dir,
            transcript_path=transcript_path,
            notes_path=notes_path,
        )
        if repaired:
            _set_status(config.meeting_id, status="completed", error=f"recovered after: {exc}")
        else:
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
    from tempa.meet.admission import wait_for_meet_admission
    from tempa.meet.joiner import join_meet
    from tempa.meet.lifecycle import MeetingEndTracker, calendar_start_timestamp, check_meeting_ended
    from tempa.meet.pipeline import setup_pipeline
    from tempa.meet.recording_ui import show_recording_notice
    from tempa.meet.session_registry import register_session, unregister_session
    from tempa.meet.storage import LocalStorageAdapter
    from tempa.meet.system_recorder import SystemMeetingRecorder, use_system_capture
    from tempa.meet.audio_convert import pcm_to_wav
    import time

    settings = get_settings()
    system_capture = use_system_capture()
    browser_audio = settings.meet_browser_audio_fallback or not system_capture

    if stt_adapter is None:
        stt_adapter = create_stt_adapter("groq")

    storage_adapter = LocalStorageAdapter()
    safe_id = config.meeting_id.replace("/", "_").replace("\\", "_")
    meeting_base_dir = os.path.join(config.output_dir, safe_id)
    screenshot_dir = config.join.screenshot_dir or os.path.join(meeting_base_dir, "screenshots")
    video_save_path: str | None = None
    if config.video.record_enabled and not system_capture:
        video_dir = os.path.join(meeting_base_dir, "video")
        os.makedirs(video_dir, exist_ok=True)
        video_save_path = os.path.join(video_dir, f"{safe_id}.webm")
        logger.info(
            "GMEET: Playwright video recording for %s (%sx%s → %s)",
            config.meeting_id,
            config.video.width,
            config.video.height,
            video_save_path,
        )
    elif config.video.record_enabled and system_capture:
        logger.info(
            "GMEET: system AV capture for %s (%sx%s fps=%s)",
            config.meeting_id,
            config.video.width,
            config.video.height,
            settings.meet_system_capture_fps,
        )

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
        video_save_path=video_save_path,
        record_video_size=(config.video.width, config.video.height) if video_save_path else None,
        virtual_camera_path=config.join.virtual_camera_path,
        screen_share_test=bool(config.av_test_youtube_url),
        display=config.join.display,
        pulse_sink=config.join.pulse_sink,
    )
    admitted = await wait_for_meet_admission(
        session.page,
        meet_url=config.meet_url,
        title=title,
    )
    if not admitted:
        await session.close()
        raise RuntimeError("Timed out waiting for Meet admission — admit Tempa from the participant list")

    from tempa.meet.joiner import dismiss_meet_popups, ensure_camera_enabled, wait_until_meet_connected

    await wait_until_meet_connected(session.page)
    await dismiss_meet_popups(session.page)
    if config.join.virtual_camera_path:
        await ensure_camera_enabled(session.page)

    if config.join.disable_mic:
        from tempa.meet.joiner import ensure_mic_disabled

        await ensure_mic_disabled(session.page)

    register_session(config.meeting_id, session.page, meet_url=config.meet_url, title=title)
    await show_recording_notice(session.page)

    av_player = None
    if config.av_test_youtube_url:
        from tempa.meet.av_test import run_av_test, stop_youtube_player

        av_dir = Path(meeting_base_dir) / "av_test"
        av_player = await run_av_test(
            session.page,
            config.av_test_youtube_url,
            av_dir,
            duration_seconds=config.duration_seconds,
            display=config.join.display,
            pulse_sink=config.join.pulse_sink,
        )

    pipeline = await setup_pipeline(
        session,
        meeting_id=config.meeting_id,
        audio=config.audio,
        stt=config.stt,
        output_dir=config.output_dir,
        storage_adapter=storage_adapter,
        stt_adapter=stt_adapter,
        use_browser_audio=browser_audio,
    )

    system_recorder: SystemMeetingRecorder | None = None
    if system_capture:
        slot_display = (config.join.display or os.environ.get("DISPLAY", ":99")).strip() or ":99"
        if not slot_display.startswith(":"):
            slot_display = f":{slot_display}"
        system_recorder = SystemMeetingRecorder(
            config.meeting_id,
            Path(meeting_base_dir),
            width=config.video.width,
            height=config.video.height,
            fps=settings.meet_system_capture_fps,
            display=slot_display,
            pulse_source=config.pulse_monitor_source or "",
        )

        async def _on_system_pcm(chunk: bytes) -> None:
            if pipeline.stt_adapter:
                await pipeline.stt_adapter.send_audio(chunk)

        system_recorder.on_pcm_chunk = _on_system_pcm
        await system_recorder.start()

    audio_monitor: asyncio.Task | None = None
    if browser_audio:
        from tempa.meet.audio_capture import monitor_audio_capture_health

        audio_monitor = asyncio.create_task(monitor_audio_capture_health(session.page, config.meeting_id))

    end_tracker = MeetingEndTracker(alone_grace_seconds=float(settings.meet_alone_grace_seconds))
    event_start_ts = calendar_start_timestamp(config.calendar_event_start)
    start_time = time.time()
    try:
        while True:
            await asyncio.sleep(30)
            if config.join.virtual_camera_path:
                from tempa.meet.joiner import ensure_camera_enabled

                await ensure_camera_enabled(session.page, retries=1)
            if await check_meeting_ended(
                session.page, tracker=end_tracker, event_start_ts=event_start_ts
            ):
                break
            elapsed = time.time() - start_time
            from tempa.meet.lifecycle import MEET_HARD_MAX_SECONDS, get_human_participant_count

            if elapsed >= MEET_HARD_MAX_SECONDS:
                logger.info("GMEET: hard max duration reached (%.0fs)", elapsed)
                break
            if elapsed >= config.duration_seconds:
                # Soft calendar duration: stay if humans are still present.
                humans = await get_human_participant_count(session.page)
                if humans <= 0:
                    logger.info("GMEET: calendar duration reached and no humans left")
                    break
    finally:
        if audio_monitor:
            audio_monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await audio_monitor
        if system_recorder:
            rec_result = await system_recorder.stop()
            pcm_path = system_recorder.pcm_path
            if pcm_path and pcm_path.exists():
                wav_path = pcm_path.with_suffix(".wav")
                with contextlib.suppress(Exception):
                    pcm_to_wav(pcm_path, wav_path, sample_rate=config.audio.sample_rate)
            logger.info("GMEET: system capture result %s", rec_result)
        await pipeline.close()
        if config.av_test_youtube_url:
            from tempa.meet.av_test import stop_youtube_player

            stop_youtube_player(av_player)
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


def _resolve_av_test_youtube_url(url: str | None) -> str | None:
    cleaned = (url or "").strip()
    if not cleaned:
        return None
    if not get_settings().meet_av_test_enabled:
        raise RuntimeError(
            "AV test mode is disabled. Set MEET_AV_TEST_ENABLED=true to run YouTube capture tests."
        )
    if "youtube.com" not in cleaned and "youtu.be" not in cleaned:
        raise RuntimeError("av_test_youtube_url must be a YouTube link")
    return cleaned


def _clamp_duration_seconds(duration_seconds: int) -> int:
    return max(60, min(int(duration_seconds), 28800))


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
    organizer_email: str | None = None,
    duration_seconds: int = 3600,
    av_test_youtube_url: str | None = None,
) -> str:
    if not has_recording_consent():
        raise RuntimeError("Recording consent not granted. Enable via dashboard, extension, or `tempa setup`.")

    duration_seconds = _clamp_duration_seconds(duration_seconds)
    av_test_youtube_url = _resolve_av_test_youtube_url(av_test_youtube_url)

    meta = {
        "calendar_event_id": calendar_event_id,
        "calendar_event_start": calendar_event_start,
        "calendar_event_end": calendar_event_end,
        "attendee_emails": attendee_emails or [],
        "organizer_email": organizer_email,
        "duration_seconds": duration_seconds,
        "av_test_youtube_url": av_test_youtube_url,
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
        organizer_email=organizer_email,
        av_test_youtube_url=av_test_youtube_url,
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
    organizer_email: str | None = None,
    duration_seconds: int = 3600,
    av_test_youtube_url: str | None = None,
) -> str:
    if not has_recording_consent():
        raise RuntimeError("Recording consent not granted. Enable via dashboard, extension, or `tempa setup`.")

    duration_seconds = _clamp_duration_seconds(duration_seconds)
    av_test_youtube_url = _resolve_av_test_youtube_url(av_test_youtube_url)

    meta = {
        "calendar_event_id": calendar_event_id,
        "calendar_event_start": calendar_event_start,
        "calendar_event_end": calendar_event_end,
        "attendee_emails": attendee_emails or [],
        "organizer_email": organizer_email,
        "duration_seconds": duration_seconds,
        "av_test_youtube_url": av_test_youtube_url,
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
        organizer_email=organizer_email,
        av_test_youtube_url=av_test_youtube_url,
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


def get_live_meeting_views() -> list[dict[str, Any]]:
    """Active jobs plus calendar events in the auto-join window (for the Live Meeting tab)."""
    from tempa.channels.calendar.poller import find_triggerable_meet_events
    from tempa.meet.archive import read_live_meeting_state
    from tempa.meet.job_store import latest_job_for_url

    jobs = get_meeting_jobs()
    active_ids = get_active_meeting_ids()
    seen_urls: set[str] = set()
    live: list[dict[str, Any]] = []

    for mid in active_ids:
        row = jobs.get(mid, {})
        url = str(row.get("meet_url") or "")
        if url:
            seen_urls.add(url)
        live.append(
            {
                "meeting_id": mid,
                "title": row.get("title", ""),
                "meet_url": url,
                "status": row.get("status", "unknown"),
                **read_live_meeting_state(mid),
            }
        )

    for ev in find_triggerable_meet_events():
        url = ev.meet_url or ""
        if not url or url in seen_urls:
            continue
        latest = latest_job_for_url(url)
        if latest:
            mid, row = latest
            seen_urls.add(url)
            live.append(
                {
                    "meeting_id": mid,
                    "title": row.get("title") or ev.summary,
                    "meet_url": url,
                    "status": row.get("status", "scheduled"),
                    "calendar_start": ev.start.isoformat(),
                    "calendar_end": ev.end.isoformat(),
                    **read_live_meeting_state(mid),
                }
            )
        else:
            seen_urls.add(url)
            live.append(
                {
                    "meeting_id": "",
                    "title": ev.summary,
                    "meet_url": url,
                    "status": "scheduled",
                    "calendar_start": ev.start.isoformat(),
                    "calendar_end": ev.end.isoformat(),
                    "transcript_tail": "",
                    "live_notes": "",
                    "suggestions": [],
                }
            )
    return live


async def repair_meeting_finalize(
    meeting_id: str,
    *,
    notify_number: str | None = None,
    send_notifications: bool = True,
) -> dict[str, Any]:
    """Re-run finalization for a meeting that recorded audio/transcript but failed to finalize."""
    from tempa.meet.job_store import get_all_job_statuses

    settings = get_settings()
    safe_id = meeting_id.replace("/", "_").replace("\\", "_")
    meeting_dir = settings.meetings_dir / safe_id
    transcript_path = meeting_dir / "transcripts" / f"{safe_id}.jsonl"
    notes_path = meeting_dir / "live_notes.md"
    audio_path = _latest_pcm_path(meeting_dir)

    meta = get_all_job_statuses().get(meeting_id, {})
    meet_url = str(meta.get("meet_url") or "")
    title = str(meta.get("title") or f"Meeting {meeting_id[:8]}")
    config = build_worker_config(
        meet_url or "https://meet.google.com/unknown",
        meeting_id,
        started_at=str(meta.get("started_at") or ""),
    )
    number = notify_number if send_notifications else None
    if send_notifications and number is None:
        number = load_default_whatsapp_number() or None
    return await _finalize_meeting(
        config,
        title=title,
        transcript_path=transcript_path if transcript_path.exists() else None,
        audio_path=audio_path,
        live_notes_path=notes_path if notes_path.exists() else None,
        notify_number=number,
        send_notifications=send_notifications,
    )
