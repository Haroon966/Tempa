from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from tempa.settings import get_settings


def _cache_path() -> Path:
    return get_settings().sessions_dir / "contacts" / "contacts.json"


async def init_contacts_db() -> None:
    settings = get_settings()
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS contacts (
                id TEXT PRIMARY KEY,
                name TEXT,
                email TEXT,
                phone TEXT,
                source TEXT,
                updated_at TEXT
            )
            """
        )
        await db.execute("CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email)")
        await db.commit()


async def upsert_contacts(contacts: list[dict[str, Any]]) -> int:
    settings = get_settings()
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(settings.db_path) as db:
        for c in contacts:
            cid = c.get("id") or f"{c.get('email', '')}:{c.get('phone', '')}"
            await db.execute(
                """
                INSERT OR REPLACE INTO contacts (id, name, email, phone, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (cid, c.get("name", ""), c.get("email", ""), c.get("phone", ""), c.get("source", "google"), now),
            )
        await db.commit()

    _cache_path().parent.mkdir(parents=True, exist_ok=True)
    _cache_path().write_text(json.dumps(contacts, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(contacts)


def search_contacts(query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    import re
    import sqlite3

    settings = get_settings()
    query = query.strip()
    if not query:
        return []

    words = [w for w in re.split(r"\s+", query.lower()) if len(w) > 1]
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        if len(words) >= 2:
            conditions = " AND ".join("lower(name) LIKE ?" for _ in words)
            params = [f"%{w}%" for w in words] + [limit]
            cur = conn.execute(
                f"""
                SELECT id, name, email, phone, source, updated_at FROM contacts
                WHERE {conditions}
                ORDER BY name LIMIT ?
                """,
                params,
            )
            rows = [dict(row) for row in cur.fetchall()]
            if rows:
                return rows

        q = f"%{query.lower()}%"
        cur = conn.execute(
            """
            SELECT id, name, email, phone, source, updated_at FROM contacts
            WHERE lower(name) LIKE ? OR lower(email) LIKE ? OR phone LIKE ?
            ORDER BY name LIMIT ?
            """,
            (q, q, q, limit),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


async def list_contacts(limit: int = 100) -> list[dict[str, Any]]:
    settings = get_settings()
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, name, email, phone, source, updated_at FROM contacts ORDER BY name LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def contact_count() -> int:
    settings = get_settings()
    async with aiosqlite.connect(settings.db_path) as db:
        cur = await db.execute("SELECT COUNT(*) FROM contacts")
        row = await cur.fetchone()
    return int(row[0]) if row else 0
