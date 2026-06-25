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
    }
    for col, col_type in migrations.items():
        if col not in existing:
            await db.execute(f"ALTER TABLE meetings ADD COLUMN {col} {col_type}")


async def init_db() -> None:
    settings = get_settings()
    async with aiosqlite.connect(settings.db_path) as db:
        await _ensure_schema(db)
        await db.commit()


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
             minutes_json, minutes_status, followups_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    }
    (meeting_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    minutes = record.get("minutes") or {}
    if minutes:
        (meeting_dir / "minutes.json").write_text(json.dumps(minutes, indent=2), encoding="utf-8")
    if followups:
        (meeting_dir / "followups.json").write_text(json.dumps(followups, indent=2), encoding="utf-8")


def meeting_artifact_status(meeting_id: str) -> dict[str, bool]:
    settings = get_settings()
    safe_id = meeting_id.replace("/", "_").replace("\\", "_")
    meeting_dir = settings.meetings_dir / safe_id
    return {
        "audio": any((meeting_dir / "audio").glob("*")) if (meeting_dir / "audio").exists() else False,
        "transcript": any((meeting_dir / "transcripts").glob("*.jsonl"))
        if (meeting_dir / "transcripts").exists()
        else False,
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


async def list_meetings() -> list[dict[str, Any]]:
    settings = get_settings()
    async with aiosqlite.connect(settings.db_path) as db:
        await _ensure_schema(db)
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM meetings ORDER BY started_at DESC")
        rows = await cursor.fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["participants"] = json.loads(item.get("participants") or "[]")
        item["attendee_emails"] = json.loads(item.get("attendee_emails") or "[]")
        item["minutes"] = json.loads(item.get("minutes_json") or "{}")
        item["followups"] = json.loads(item.get("followups_json") or "[]")
        for key in ("minutes_json", "followups_json"):
            item.pop(key, None)
        item["artifacts"] = meeting_artifact_status(item["id"])
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
