from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from tempa.meet.backends.groq_backend import GroqBackend
from tempa.meet.minutes import MeetingLens
from tempa.rag.ingest import ingest_text
from tempa.rag.purge import purge_all_vectors, purge_meeting_vectors
from tempa.settings import get_settings


async def init_db() -> None:
    settings = get_settings()
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS meetings (
                id TEXT PRIMARY KEY,
                title TEXT,
                meet_link TEXT,
                started_at TEXT,
                ended_at TEXT,
                participants TEXT,
                audio_path TEXT,
                transcript_path TEXT,
                minutes_json TEXT,
                created_at TEXT
            )
            """
        )
        await db.commit()


async def save_meeting_archive(record: dict[str, Any]) -> str:
    settings = get_settings()
    meeting_id = record.get("id") or str(uuid.uuid4())
    record["id"] = meeting_id
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO meetings
            (id, title, meet_link, started_at, ended_at, participants, audio_path, transcript_path, minutes_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meeting_id,
                record.get("title", ""),
                record.get("meet_link", ""),
                record.get("started_at", ""),
                record.get("ended_at", ""),
                json.dumps(record.get("participants", [])),
                record.get("audio_path", ""),
                record.get("transcript_path", ""),
                json.dumps(record.get("minutes", {})),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()
    return meeting_id


async def list_meetings() -> list[dict[str, Any]]:
    settings = get_settings()
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM meetings ORDER BY started_at DESC")
        rows = await cursor.fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["participants"] = json.loads(item.get("participants") or "[]")
        item["minutes"] = json.loads(item.get("minutes_json") or "{}")
        del item["minutes_json"]
        results.append(item)
    return results


async def get_meeting(meeting_id: str) -> dict[str, Any] | None:
    meetings = await list_meetings()
    for m in meetings:
        if m["id"] == meeting_id:
            return m
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
