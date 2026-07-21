from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from tempa.meet.backends.groq_backend import GroqBackend
from tempa.meet.minutes import MeetingLens
from tempa.rag.ingest import ingest_text
from tempa.rag.purge import purge_all_vectors, purge_meeting_vectors
from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_MEETINGS_COLUMNS = (
    "id TEXT PRIMARY KEY",
    "title TEXT",
    "meet_link TEXT",
    "started_at TEXT",
    "ended_at TEXT",
    "participants TEXT",
    "attendee_emails TEXT",
    "calendar_event_id TEXT",
    "calendar_event_start TEXT",
    "audio_path TEXT",
    "transcript_path TEXT",
    "minutes_json TEXT",
    "minutes_status TEXT",
    "followups_json TEXT",
    "created_at TEXT",
)


async def _ensure_schema(db: aiosqlite.Connection) -> None:
    await db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS meetings (
            {", ".join(_MEETINGS_COLUMNS)}
        )
        """
    )
    cursor = await db.execute("PRAGMA table_info(meetings)")
    rows = await cursor.fetchall()
    existing = {row[1] for row in rows}
    migrations = {
        "attendee_emails": "TEXT",
        "calendar_event_id": "TEXT",
        "calendar_event_start": "TEXT",
        "minutes_status": "TEXT",
        "followups_json": "TEXT",
        "youtube_video_id": "TEXT",
        "youtube_url": "TEXT",
    }
    for col, col_type in migrations.items():
        if col not in existing:
            await db.execute(f"ALTER TABLE meetings ADD COLUMN {col} {col_type}")


async def init_db() -> None:
    settings = get_settings()
    async with aiosqlite.connect(settings.db_path) as db:
        await _ensure_schema(db)
        await db.commit()


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


def _meeting_dir_for_id(meeting_id: str) -> Path:
    safe_id = meeting_id.replace("/", "_").replace("\\", "_")
    return get_settings().meetings_dir / safe_id


def _meeting_has_archive_artifacts(meeting_dir: Path, meeting_id: str) -> bool:
    safe_id = meeting_id.replace("/", "_").replace("\\", "_")
    transcript_path = meeting_dir / "transcripts" / f"{safe_id}.jsonl"
    if transcript_path.exists() and transcript_path.stat().st_size > 0:
        return True
    if (meeting_dir / "minutes.json").exists():
        return True
    if (meeting_dir / "live_notes.md").exists() and (meeting_dir / "live_notes.md").stat().st_size > 0:
        return True
    if (meeting_dir / "manifest.json").exists():
        return True
    audio_dir = meeting_dir / "audio"
    return audio_dir.exists() and any(audio_dir.glob("*"))


async def archive_meeting_from_disk(meeting_id: str) -> bool:
    """Index a on-disk meeting folder into the SQLite archive (no LLM calls)."""
    import asyncio

    from tempa.meet.audio_convert import resolve_audio_path
    from tempa.meet.job_store import get_all_job_statuses
    from tempa.meet.media import finalize_meeting_media_files

    meeting_dir = _meeting_dir_for_id(meeting_id)
    if not meeting_dir.is_dir() or not _meeting_has_archive_artifacts(meeting_dir, meeting_id):
        return False

    await asyncio.to_thread(finalize_meeting_media_files, meeting_id)

    safe_id = meeting_id.replace("/", "_").replace("\\", "_")
    transcript_path = meeting_dir / "transcripts" / f"{safe_id}.jsonl"
    manifest_path = meeting_dir / "manifest.json"
    minutes_path = meeting_dir / "minutes.json"
    notes_path = meeting_dir / "live_notes.md"

    record: dict[str, Any] = {"id": meeting_id}
    if manifest_path.exists():
        try:
            record.update(json.loads(manifest_path.read_text(encoding="utf-8")))
        except Exception:
            logger.debug("Invalid manifest for %s", meeting_id, exc_info=True)

    meta = get_all_job_statuses().get(meeting_id, {})
    record.setdefault("title", meta.get("title") or f"Meeting {meeting_id[:8]}")
    record.setdefault("meet_link", meta.get("meet_url") or "")
    record.setdefault("started_at", meta.get("started_at") or "")
    record.setdefault("calendar_event_id", meta.get("calendar_event_id") or "")
    record.setdefault("calendar_event_start", meta.get("calendar_event_start") or "")

    transcript_text, segments = _parse_transcript_jsonl(transcript_path)
    participants = sorted({s.get("speaker") for s in segments if s.get("speaker")})

    minutes: dict[str, Any] = {}
    minutes_status = str(record.get("minutes_status") or "")
    if minutes_path.exists():
        try:
            minutes = json.loads(minutes_path.read_text(encoding="utf-8"))
            if minutes and not minutes_status:
                minutes_status = "complete"
        except Exception:
            logger.debug("Invalid minutes.json for %s", meeting_id, exc_info=True)
    if not minutes_status:
        minutes_status = "complete" if minutes else ("partial" if transcript_text.strip() else "none")

    if not record.get("ended_at"):
        ended_at = meta.get("finished_at") or meta.get("ended_at")
        if not ended_at:
            mtimes = [p.stat().st_mtime for p in meeting_dir.rglob("*") if p.is_file()]
            ended_at = (
                datetime.fromtimestamp(max(mtimes), tz=timezone.utc).isoformat() if mtimes else ""
            )
        record["ended_at"] = ended_at or record.get("started_at") or ""

    if not record.get("started_at") and transcript_path.exists():
        record["started_at"] = datetime.fromtimestamp(
            transcript_path.stat().st_mtime, tz=timezone.utc
        ).isoformat()

    wav_path = resolve_audio_path(meeting_dir, safe_id)
    audio_files = list((meeting_dir / "audio").glob("*.pcm")) if (meeting_dir / "audio").exists() else []

    record.update(
        {
            "id": meeting_id,
            "participants": participants or record.get("participants") or [],
            "attendee_emails": record.get("attendee_emails") or meta.get("attendee_emails") or [],
            "audio_path": str(wav_path or (audio_files[0] if audio_files else record.get("audio_path") or "")),
            "transcript_path": str(transcript_path) if transcript_path.exists() else "",
            "minutes": minutes,
            "minutes_status": minutes_status,
            "followups": record.get("followups") or [],
        }
    )

    await save_meeting_archive(record)
    return True


async def sync_meeting_archives_from_disk() -> int:
    """Ensure every meeting folder with artifacts has a SQLite archive row."""
    settings = get_settings()
    if not settings.meetings_dir.exists():
        return 0
    synced = 0
    for entry in settings.meetings_dir.iterdir():
        if not entry.is_dir():
            continue
        if await archive_meeting_from_disk(entry.name):
            synced += 1
    return synced


async def repair_archives_missing_minutes(*, min_segments: int = 3) -> int:
    """Generate minutes for archived meetings that have transcript but no summary."""
    repaired = 0
    for meeting in await list_meetings():
        if meeting.get("minutes_status") == "complete":
            minutes = meeting.get("minutes") or {}
            if minutes.get("tldr") or minutes.get("summary"):
                continue
        path = meeting.get("transcript_path")
        if not path:
            continue
        transcript_path = Path(path)
        if not transcript_path.exists():
            continue
        text, segments = _parse_transcript_jsonl(transcript_path)
        if len(segments) < min_segments and not text.strip():
            continue
        notes_path = _meeting_dir_for_id(meeting["id"]) / "live_notes.md"
        if notes_path.exists():
            notes = notes_path.read_text(encoding="utf-8").strip()
            if notes:
                text = f"{text}\n\n--- Live Notes ---\n{notes}".strip()
        if not text.strip():
            continue
        try:
            minutes = await generate_minutes_from_transcript(text, source_name="transcript.txt")
            meeting_dir = _meeting_dir_for_id(meeting["id"])
            record = {**meeting, "minutes": minutes, "minutes_status": "complete"}
            write_meeting_artifacts(meeting_dir, record, meeting.get("followups") or [])
            await save_meeting_archive(record)
            repaired += 1
        except Exception:
            logger.exception("Failed to repair minutes for %s", meeting["id"])
    return repaired


async def save_meeting_archive(record: dict[str, Any]) -> str:
    settings = get_settings()
    meeting_id = record.get("id") or ""
    async with aiosqlite.connect(settings.db_path) as db:
        await _ensure_schema(db)
        await db.execute(
            """
            INSERT OR REPLACE INTO meetings
            (id, title, meet_link, started_at, ended_at, participants, attendee_emails,
             calendar_event_id, calendar_event_start, audio_path, transcript_path,
             minutes_json, minutes_status, followups_json, youtube_video_id, youtube_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meeting_id,
                record.get("title", ""),
                record.get("meet_link", ""),
                record.get("started_at", ""),
                record.get("ended_at", ""),
                json.dumps(record.get("participants", [])),
                json.dumps(record.get("attendee_emails", [])),
                record.get("calendar_event_id", ""),
                record.get("calendar_event_start", ""),
                record.get("audio_path", ""),
                record.get("transcript_path", ""),
                json.dumps(record.get("minutes", {})),
                record.get("minutes_status", ""),
                json.dumps(record.get("followups", [])),
                record.get("youtube_video_id", ""),
                record.get("youtube_url", ""),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()
    return meeting_id


def write_meeting_artifacts(
    meeting_dir: Path,
    record: dict[str, Any],
    followups: list[dict[str, Any]],
) -> None:
    meeting_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": record.get("id"),
        "title": record.get("title"),
        "meet_link": record.get("meet_link"),
        "started_at": record.get("started_at"),
        "ended_at": record.get("ended_at"),
        "participants": record.get("participants", []),
        "attendee_emails": record.get("attendee_emails", []),
        "calendar_event_id": record.get("calendar_event_id"),
        "calendar_event_start": record.get("calendar_event_start"),
        "minutes_status": record.get("minutes_status"),
        "youtube_video_id": record.get("youtube_video_id"),
        "youtube_url": record.get("youtube_url"),
    }
    (meeting_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    minutes = record.get("minutes") or {}
    if minutes:
        (meeting_dir / "minutes.json").write_text(json.dumps(minutes, indent=2), encoding="utf-8")
    if followups:
        (meeting_dir / "followups.json").write_text(json.dumps(followups, indent=2), encoding="utf-8")


def meeting_artifact_status(meeting_id: str) -> dict[str, bool]:
    from tempa.meet.media import list_meeting_media

    settings = get_settings()
    safe_id = meeting_id.replace("/", "_").replace("\\", "_")
    meeting_dir = settings.meetings_dir / safe_id
    media = list_meeting_media(meeting_id)
    return {
        "audio": media["has_audio"],
        "video": media["has_video"],
        "transcript": media["has_transcript"],
        "minutes": (meeting_dir / "minutes.json").exists(),
        "manifest": (meeting_dir / "manifest.json").exists(),
        "followups": (meeting_dir / "followups.json").exists(),
    }


async def apply_meet_retention_policy() -> int:
    settings = get_settings()
    days = int(getattr(settings, "meet_retention_days", 0) or 0)
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    removed = 0
    for meeting in await list_meetings():
        ended = meeting.get("ended_at") or meeting.get("started_at") or ""
        try:
            dt = datetime.fromisoformat(ended.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < cutoff:
                if await delete_meeting(meeting["id"]):
                    removed += 1
        except Exception:
            continue
    return removed


async def count_meetings() -> int:
    settings = get_settings()
    async with aiosqlite.connect(settings.db_path) as db:
        await _ensure_schema(db)
        cursor = await db.execute("SELECT COUNT(*) FROM meetings")
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def list_meetings(
    *,
    limit: int | None = None,
    include_artifacts: bool = True,
) -> list[dict[str, Any]]:
    return await _list_meetings_from_db(limit=limit, include_artifacts=include_artifacts)


def _row_to_meeting(row: dict[str, Any], *, include_artifacts: bool) -> dict[str, Any]:
    item = dict(row)
    item["participants"] = json.loads(item.get("participants") or "[]")
    item["attendee_emails"] = json.loads(item.get("attendee_emails") or "[]")
    item["minutes"] = json.loads(item.get("minutes_json") or "{}")
    item["followups"] = json.loads(item.get("followups_json") or "[]")
    for key in ("minutes_json", "followups_json"):
        item.pop(key, None)
    if include_artifacts:
        try:
            item["artifacts"] = meeting_artifact_status(item["id"])
        except OSError:
            item["artifacts"] = {
                "audio": False,
                "video": False,
                "transcript": False,
                "minutes": False,
                "manifest": False,
                "followups": False,
            }
    return item


async def _list_meetings_from_db(
    *,
    limit: int | None = None,
    include_artifacts: bool = True,
    meeting_id: str | None = None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    query = "SELECT * FROM meetings"
    params: list[Any] = []
    if meeting_id:
        query += " WHERE id = ?"
        params.append(meeting_id)
    query += " ORDER BY started_at DESC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    async with aiosqlite.connect(settings.db_path) as db:
        await _ensure_schema(db)
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
    return [_row_to_meeting(dict(row), include_artifacts=include_artifacts) for row in rows]


async def get_meeting(meeting_id: str) -> dict[str, Any] | None:
    rows = await _list_meetings_from_db(meeting_id=meeting_id, include_artifacts=True)
    if rows:
        return rows[0]
    if await archive_meeting_from_disk(meeting_id):
        rows = await _list_meetings_from_db(meeting_id=meeting_id, include_artifacts=True)
        if rows:
            return rows[0]
    return None


def get_latest_meeting_context() -> str:
    """Sync helper for WhatsApp grounding — latest archived meeting summary."""
    settings = get_settings()
    if not settings.db_path.exists():
        return ""
    try:
        conn = sqlite3.connect(settings.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT title, meet_link, started_at, ended_at, participants, minutes_json "
            "FROM meetings ORDER BY COALESCE(ended_at, started_at, created_at) DESC LIMIT 1"
        ).fetchone()
        conn.close()
    except Exception:
        return ""
    if not row:
        return ""
    participants = json.loads(row["participants"] or "[]")
    minutes = json.loads(row["minutes_json"] or "{}")
    tldr = minutes.get("tldr") or minutes.get("summary") or ""
    lines = [
        f"Title: {row['title'] or 'Untitled'}",
        f"Meet link: {row['meet_link'] or 'n/a'}",
        f"Started: {row['started_at'] or 'unknown'}",
        f"Ended: {row['ended_at'] or 'unknown'}",
    ]
    if participants:
        lines.append(f"Participants: {', '.join(participants)}")
    if tldr:
        lines.append(f"Minutes TL;DR: {tldr[:800]}")
    return "\n".join(lines)


def _truncate_meeting_tldr(text: str, limit: int = 200) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def get_recent_meetings_context(*, limit: int = 3) -> str:
    """Compact summary of recent archived meetings for always-on grounding."""
    settings = get_settings()
    if not settings.db_path.exists():
        return ""
    try:
        conn = sqlite3.connect(settings.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT title, started_at, ended_at, minutes_json, calendar_event_id "
            "FROM meetings ORDER BY COALESCE(ended_at, started_at, created_at) DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
    except Exception:
        return ""
    if not rows:
        return ""
    lines: list[str] = ["Recent meeting archives:"]
    for row in rows:
        minutes = json.loads(row["minutes_json"] or "{}")
        tldr = minutes.get("tldr") or minutes.get("summary") or "no minutes"
        when = row["started_at"] or row["ended_at"] or "unknown"
        lines.append(f"- {row['title'] or 'Untitled'} ({when}): {_truncate_meeting_tldr(str(tldr))}")
    return "\n".join(lines)


def get_meetings_index_by_calendar_id() -> dict[str, dict[str, Any]]:
    """Map calendar_event_id → {title, tldr, action_items_count}."""
    settings = get_settings()
    if not settings.db_path.exists():
        return {}
    try:
        conn = sqlite3.connect(settings.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT title, calendar_event_id, minutes_json FROM meetings "
            "WHERE calendar_event_id IS NOT NULL AND calendar_event_id != ''"
        ).fetchall()
        conn.close()
    except Exception:
        return {}
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        cid = str(row["calendar_event_id"])
        minutes = json.loads(row["minutes_json"] or "{}")
        tldr = minutes.get("tldr") or minutes.get("summary") or ""
        action_items = minutes.get("action_items") or []
        index[cid] = {
            "title": row["title"] or "",
            "tldr": tldr,
            "action_items_count": len(action_items) if isinstance(action_items, list) else 0,
        }
    return index


async def delete_meeting(meeting_id: str) -> bool:
    settings = get_settings()
    meeting = await get_meeting(meeting_id)
    async with aiosqlite.connect(settings.db_path) as db:
        cursor = await db.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
        await db.commit()
        deleted = cursor.rowcount > 0
    if deleted:
        meeting_dir = settings.meetings_dir / meeting_id.replace("/", "_").replace("\\", "_")
        if meeting_dir.exists():
            import shutil

            shutil.rmtree(meeting_dir, ignore_errors=True)
        purge_meeting_vectors(meeting_id)
    return deleted


async def erase_all_user_data() -> dict[str, Any]:
    """SEC-06: GDPR right-to-erasure."""
    settings = get_settings()
    meetings = await list_meetings()
    for m in meetings:
        await delete_meeting(m["id"])
    purge_all_vectors()
    import shutil

    for sub in ("meetings", "vector"):
        path = settings.tempa_data_dir / sub if sub != "vector" else settings.vector_dir
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True, exist_ok=True)
    return {"erased": True, "meetings_removed": len(meetings)}


async def export_user_data() -> dict[str, Any]:
    settings = get_settings()
    meetings = await list_meetings()
    transcripts: dict[str, str] = {}
    for m in meetings:
        path = m.get("transcript_path")
        if path and Path(path).exists():
            transcripts[m["id"]] = Path(path).read_text(encoding="utf-8")
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "meetings": meetings,
        "transcripts": transcripts,
        "rag_chunks": get_store().count(),
    }


def get_store():
    from tempa.rag.store import get_store as _get_store

    return _get_store()


async def generate_minutes_from_transcript(transcript_text: str, source_name: str = "transcript.txt") -> dict[str, Any]:
    lens = MeetingLens(GroqBackend())
    summary = await lens.run(transcript_text, source_name=source_name)
    return summary.model_dump()


async def index_meeting_to_rag(record: dict[str, Any], transcript_text: str) -> None:
    minutes = record.get("minutes", {})
    summary = minutes.get("tldr") or minutes.get("summary", "")
    ingest_result = ingest_text(
        transcript_text,
        tool="meet",
        source=record.get("id", "unknown"),
        participants=record.get("participants"),
        meet_link=record.get("meet_link"),
        title=record.get("title", ""),
        tags=["transcript"],
    )
    record["rag_chunk_ids"] = ingest_result.get("chunk_ids", [])
    if summary:
        ingest_text(
            summary,
            tool="meet",
            source=f"{record.get('id', 'unknown')}:minutes",
            participants=record.get("participants"),
            meet_link=record.get("meet_link"),
            title=record.get("title", ""),
            tags=["minutes"],
        )


def read_live_meeting_state(meeting_id: str) -> dict[str, Any]:
    settings = get_settings()
    safe_id = meeting_id.replace("/", "_").replace("\\", "_")
    meeting_dir = settings.meetings_dir / safe_id
    transcript_path = meeting_dir / "transcripts" / f"{safe_id}.jsonl"
    notes_path = meeting_dir / "live_notes.md"
    suggestions_path = meeting_dir / "suggestions.jsonl"

    transcript_tail = ""
    if transcript_path.exists():
        lines: list[str] = []
        for raw in transcript_path.read_text(encoding="utf-8").splitlines()[-40:]:
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if row.get("type") == "segment" and row.get("text"):
                speaker = row.get("speaker") or "Unknown"
                lines.append(f"{speaker}: {row['text']}")
        transcript_tail = "\n".join(lines)

    notes = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""
    suggestions: list[dict[str, Any]] = []
    if suggestions_path.exists():
        for raw in suggestions_path.read_text(encoding="utf-8").splitlines()[-10:]:
            try:
                suggestions.append(json.loads(raw))
            except json.JSONDecodeError:
                continue

    return {
        "meeting_id": meeting_id,
        "transcript_tail": transcript_tail,
        "live_notes": notes,
        "suggestions": suggestions,
    }
