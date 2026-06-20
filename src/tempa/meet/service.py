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
)
from tempa.meet.audio_convert import resolve_audio_path
from tempa.meet.config import AudioConfig, JoinConfig, SttConfig, WorkerConfig
from tempa.meet.consent import has_recording_consent
from tempa.meet.job_store import (
    enqueue_meet_job,
    get_all_job_statuses,
    update_job_status,
)
from tempa.meet.notes import live_notes_loop
from tempa.meet.stt.factory import create_stt_adapter
from tempa.meet.worker import run_meeting_worker
from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_active_jobs: dict[str, asyncio.Task] = {}
_job_status: dict[str, dict[str, Any]] = {}


def _delegate_to_worker() -> bool:
    return os.environ.get("TEMPA_MEET_DELEGATE_TO_WORKER", "").lower() in ("1", "true", "yes")


def build_worker_config(meet_url: str, meeting_id: str | None = None) -> WorkerConfig:
    settings = get_settings()
    mid = meeting_id or str(uuid.uuid4())
    return WorkerConfig(
        meeting_id=mid,
        meet_url=meet_url,
        output_dir=str(settings.meetings_dir),
        duration_seconds=3600,
        audio=AudioConfig(debug=True),
        stt=SttConfig(provider="groq", extra={"chunk_seconds": 15.0, "language": "en"}),
        join=JoinConfig(
            headless=True,
            storage_state_path=str(settings.google_storage_state_path),
            bot_name="Tempa",
            disable_mic=True,
            disable_camera=True,
        ),
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


async def _finalize_meeting(
    meeting_id: str,
    meet_url: str,
    title: str,
    transcript_path: Path | None,
    audio_path: Path | None,
    live_notes_path: Path | None,
    notify_number: str | None,
) -> dict[str, Any]:
    transcript_text, segments = _parse_transcript_jsonl(transcript_path) if transcript_path else ("", [])
    if live_notes_path and live_notes_path.exists():
        live_notes = live_notes_path.read_text(encoding="utf-8")
        if live_notes:
            transcript_text = f"{transcript_text}\n\n--- Live Notes ---\n{live_notes}"

    minutes: dict[str, Any] = {}
    if transcript_text.strip():
        try:
            minutes = await generate_minutes_from_transcript(transcript_text, source_name="meeting.jsonl")
        except Exception:
            logger.exception("Minutes generation failed for %s", meeting_id)

    participants = sorted({s.get("speaker") for s in segments if s.get("speaker")})
    wav_path: Path | None = None
    if audio_path and audio_path.exists():
        meeting_dir = audio_path.parent.parent if audio_path.parent.name == "audio" else audio_path.parent
        wav_path = resolve_audio_path(meeting_dir, meeting_id)
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "id": meeting_id,
        "title": title or f"Meeting {meeting_id[:8]}",
        "meet_link": meet_url,
        "started_at": now,
        "ended_at": now,
        "participants": participants,
        "audio_path": str(wav_path or audio_path or ""),
        "transcript_path": str(transcript_path) if transcript_path else "",
        "minutes": minutes,
    }
    await save_meeting_archive(record)
    if transcript_text.strip():
        await index_meeting_to_rag(record, transcript_text)

    summary = minutes.get("tldr") or minutes.get("summary") or "Meeting completed."
    if notify_number:
        msg = f"*{record['title']}* ended.\n\n{summary}"
        if record.get("meet_link"):
            msg += f"\n\nLink: {record['meet_link']}"
        await send_whatsapp_message(notify_number, msg[:3500], source_channel="whatsapp_auto_reply")

    await event_bus.publish_json("meet", "completed", meeting_id)
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
    audio_glob = list((meeting_dir / "audio").glob("*.pcm")) if (meeting_dir / "audio").exists() else []

    stop_notes = asyncio.Event()
    notes_task = asyncio.create_task(live_notes_loop(transcript_path, notes_path, stop_notes))

    _set_status(config.meeting_id, status="running", meet_url=config.meet_url)
    try:
        stt = create_stt_adapter("groq")
        await run_meeting_worker(config, stt_adapter=stt)
        _set_status(config.meeting_id, status="finalizing")
        await _finalize_meeting(
            config.meeting_id,
            config.meet_url,
            title,
            transcript_path if transcript_path.exists() else None,
            audio_glob[0] if audio_glob else None,
            notes_path,
            notify_number or load_default_whatsapp_number() or None,
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
        stop_notes.set()
        notes_task.cancel()
        _active_jobs.pop(config.meeting_id, None)


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
) -> str:
    if not has_recording_consent():
        raise RuntimeError("Recording consent not granted. Enable via dashboard, extension, or `tempa setup`.")

    if _delegate_to_worker():
        mid = enqueue_meet_job(
            meet_url,
            title=title,
            meeting_id=meeting_id,
            notify_number=notify_number,
        )
        _job_status[mid] = {"status": "queued", "meet_url": meet_url, "title": title}
        return mid

    config = build_worker_config(meet_url, meeting_id)
    if config.meeting_id in _active_jobs:
        return config.meeting_id

    task = asyncio.create_task(
        _run_meeting_job(config, title=title, notify_number=notify_number),
        name=f"meet-{config.meeting_id}",
    )
    _active_jobs[config.meeting_id] = task
    _set_status(config.meeting_id, status="queued", meet_url=meet_url, title=title)
    return config.meeting_id


def schedule_meeting_join(
    meet_url: str,
    *,
    title: str = "",
    meeting_id: str | None = None,
    notify_number: str | None = None,
) -> str:
    if not has_recording_consent():
        raise RuntimeError("Recording consent not granted. Enable via dashboard, extension, or `tempa setup`.")

    if _delegate_to_worker():
        mid = enqueue_meet_job(
            meet_url,
            title=title,
            meeting_id=meeting_id,
            notify_number=notify_number,
        )
        _job_status[mid] = {"status": "queued", "meet_url": meet_url, "title": title}
        return mid

    config = build_worker_config(meet_url, meeting_id)
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

    _set_status(config.meeting_id, status="queued", meet_url=meet_url, title=title)
    return config.meeting_id


def get_meeting_jobs() -> dict[str, dict[str, Any]]:
    merged = get_all_job_statuses()
    merged.update(_job_status)
    return merged
