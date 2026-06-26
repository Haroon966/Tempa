from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.settings import get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_state (
 id TEXT PRIMARY KEY DEFAULT 'global',
 last_sync_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z'
);
INSERT OR IGNORE INTO sync_state (id) VALUES ('global');

CREATE TABLE IF NOT EXISTS tick_lock (
 id TEXT PRIMARY KEY DEFAULT 'global',
 locked_at TEXT NOT NULL,
 locked_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
 id TEXT PRIMARY KEY,
 source TEXT NOT NULL,
 type TEXT NOT NULL,
 context_key TEXT NOT NULL,
 payload TEXT NOT NULL DEFAULT '{}',
 status TEXT NOT NULL DEFAULT 'pending',
 priority TEXT NOT NULL DEFAULT 'normal',
 received_at TEXT NOT NULL,
 processed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_status_ctx ON events(status, context_key);

CREATE TABLE IF NOT EXISTS entities (
 id TEXT PRIMARY KEY,
 source TEXT NOT NULL,
 external_id TEXT NOT NULL,
 type TEXT NOT NULL,
 url TEXT,
 created_at TEXT NOT NULL,
 UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS links (
 entity_a TEXT NOT NULL,
 entity_b TEXT NOT NULL,
 relationship TEXT NOT NULL,
 created_at TEXT NOT NULL,
 created_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
 id TEXT PRIMARY KEY,
 context_key TEXT NOT NULL,
 status TEXT NOT NULL,
 intent TEXT,
 phase TEXT DEFAULT 'manager',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 completed_at TEXT,
 pr_url TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_ctx_status ON sessions(context_key, status);

CREATE TABLE IF NOT EXISTS tickets (
 id TEXT PRIMARY KEY,
 title TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'open',
 origin_channel TEXT NOT NULL DEFAULT '',
 origin_thread TEXT NOT NULL DEFAULT '',
 payload TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
"""

_db_lock = threading.Lock()


def harness_db_path() -> Path:
    settings = get_settings()
    path = settings.varys_harness_db
    if not path.is_absolute():
        path = (settings.project_root / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(harness_db_path()), check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(_SCHEMA)
    db.commit()
    return db


def acquire_tick_lock(db: sqlite3.Connection, caller: str) -> bool:
    with _db_lock:
        db.execute(
            "DELETE FROM tick_lock WHERE id='global' "
            "AND (CAST(strftime('%s','now') AS INTEGER) "
            " - CAST(strftime('%s', locked_at) AS INTEGER)) > 1800"
        )
        db.commit()
        lock_id = f"{caller}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
        db.execute(
            "INSERT OR IGNORE INTO tick_lock (id, locked_at, locked_by) "
            "VALUES ('global', datetime('now'), ?)",
            (lock_id,),
        )
        db.commit()
        return db.execute("SELECT changes()").fetchone()[0] > 0


def release_tick_lock(db: sqlite3.Connection) -> None:
    with _db_lock:
        db.execute("DELETE FROM tick_lock WHERE id='global'")
        db.commit()


def get_last_sync_at(db: sqlite3.Connection) -> str:
    row = db.execute("SELECT last_sync_at FROM sync_state WHERE id='global'").fetchone()
    return row[0] if row else "1970-01-01T00:00:00Z"


def set_last_sync_at(db: sqlite3.Connection, ts: str) -> None:
    with _db_lock:
        db.execute("UPDATE sync_state SET last_sync_at=? WHERE id='global'", (ts,))
        db.commit()


def register_entity(
    db: sqlite3.Connection,
    source: str,
    external_id: str,
    entity_type: str,
    url: str = "",
) -> str:
    with _db_lock:
        existing = db.execute(
            "SELECT id FROM entities WHERE source=? AND external_id=?",
            (source, external_id),
        ).fetchone()
        if existing:
            return existing[0]
        entity_id = str(uuid.uuid4())
        db.execute(
            "INSERT OR IGNORE INTO entities (id, source, external_id, type, url, created_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (entity_id, source, external_id, entity_type, url or ""),
        )
        db.commit()
        return entity_id


def insert_event(
    db: sqlite3.Connection,
    *,
    event_id: str,
    source: str,
    event_type: str,
    context_key: str,
    payload: dict[str, Any] | None = None,
    priority: str = "normal",
) -> bool:
    with _db_lock:
        db.execute(
            "INSERT OR IGNORE INTO events "
            "(id, source, type, context_key, payload, status, priority, received_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?, datetime('now'))",
            (event_id, source, event_type, context_key, json.dumps(payload or {}), priority),
        )
        db.commit()
        return db.execute("SELECT changes()").fetchone()[0] > 0


def pending_context_keys(db: sqlite3.Connection) -> list[str]:
    rows = db.execute(
        "SELECT DISTINCT context_key FROM events WHERE status='pending' ORDER BY context_key"
    ).fetchall()
    return [r[0] for r in rows]


def pending_events_for_context(db: sqlite3.Connection, context_key: str) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT id, source, type, payload, priority FROM events "
        "WHERE context_key=? AND status='pending' ORDER BY received_at",
        (context_key,),
    ).fetchall()
    return [
        {
            "id": r[0],
            "source": r[1],
            "type": r[2],
            "payload": json.loads(r[3] or "{}"),
            "priority": r[4],
        }
        for r in rows
    ]


def has_running_session(db: sqlite3.Connection, context_key: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM sessions WHERE context_key=? AND status='running' LIMIT 1",
        (context_key,),
    ).fetchone()
    return row is not None


def create_session(
    db: sqlite3.Connection,
    *,
    context_key: str,
    intent: str = "",
    phase: str = "manager",
) -> str:
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _db_lock:
        db.execute(
            "INSERT INTO sessions (id, context_key, status, intent, phase, created_at, updated_at) "
            "VALUES (?, ?, 'running', ?, ?, ?, ?)",
            (session_id, context_key, intent, phase, now, now),
        )
        db.commit()
    return session_id


def mark_events_processing(db: sqlite3.Connection, context_key: str) -> None:
    with _db_lock:
        db.execute(
            "UPDATE events SET status='processing' WHERE context_key=? AND status='pending'",
            (context_key,),
        )
        db.commit()


def complete_events(db: sqlite3.Connection, context_key: str) -> None:
    with _db_lock:
        db.execute(
            "UPDATE events SET status='done', processed_at=datetime('now') "
            "WHERE context_key=? AND status IN ('pending', 'processing')",
            (context_key,),
        )
        db.commit()


def finish_session(db: sqlite3.Connection, session_id: str, *, status: str = "done") -> None:
    with _db_lock:
        db.execute(
            "UPDATE sessions SET status=?, updated_at=?, completed_at=datetime('now') WHERE id=?",
            (status, datetime.now(timezone.utc).isoformat(), session_id),
        )
        db.commit()


def update_ticket_status(db: sqlite3.Connection, ticket_id: str, status: str) -> bool:
    with _db_lock:
        db.execute(
            "UPDATE tickets SET status=?, updated_at=? WHERE id=?",
            (status, datetime.now(timezone.utc).isoformat(), ticket_id),
        )
        db.commit()
        return db.execute("SELECT changes()").fetchone()[0] > 0


def get_ticket(db: sqlite3.Connection, ticket_id: str) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT id, title, status, origin_channel, origin_thread, payload FROM tickets WHERE id=?",
        (ticket_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "title": row[1],
        "status": row[2],
        "origin_channel": row[3],
        "origin_thread": row[4],
        "payload": json.loads(row[5] or "{}"),
    }


def approve_varys_ticket(ticket_id: str) -> dict[str, Any]:
    """Owner approval from dashboard — enqueue go signal and mark ticket in progress."""
    db = get_db()
    try:
        ticket = get_ticket(db, ticket_id)
        if not ticket:
            return {"status": "error", "reason": "ticket_not_found"}
        if ticket["status"] not in {"open", "in_progress"}:
            return {"status": "error", "reason": f"ticket_status_{ticket['status']}"}

        channel = ticket.get("origin_channel") or "dashboard"
        thread_ts = ticket.get("origin_thread") or "main"
        origin = f"{channel}-{thread_ts}"
        entity_id = register_entity(db, channel, origin, "thread")
        inserted = insert_event(
            db,
            event_id=f"{channel}-go-{ticket_id}",
            source=channel,
            event_type="message.go_signal",
            context_key=entity_id,
            payload={
                "ticket_id": ticket_id,
                "thread_ts": thread_ts,
                "channel": channel,
                "title": ticket.get("title", ""),
            },
            priority="high",
        )
        update_ticket_status(db, ticket_id, "in_progress")
        return {
            "status": "approved",
            "ticket_id": ticket_id,
            "event_enqueued": inserted,
            "message": "Approved — work will proceed on the next orchestrator tick.",
        }
    finally:
        db.close()


def create_ticket(
    db: sqlite3.Connection,
    *,
    title: str,
    origin_channel: str = "",
    origin_thread: str = "",
    payload: dict[str, Any] | None = None,
) -> str:
    ticket_id = f"ticket-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    with _db_lock:
        db.execute(
            "INSERT INTO tickets (id, title, status, origin_channel, origin_thread, payload, created_at, updated_at) "
            "VALUES (?, ?, 'open', ?, ?, ?, ?, ?)",
            (
                ticket_id,
                title[:500],
                origin_channel,
                origin_thread,
                json.dumps(payload or {}),
                now,
                now,
            ),
        )
        db.commit()
    entity_id = register_entity(db, "tempa", ticket_id, "ticket", f"tempa:{ticket_id}")
    insert_event(
        db,
        event_id=f"tempa-{ticket_id}",
        source="tempa",
        event_type="ticket.created",
        context_key=entity_id,
        payload={"id": ticket_id, "title": title, "status": "open"},
    )
    return ticket_id


def harness_status() -> dict[str, Any]:
    db = get_db()
    try:
        pending = db.execute("SELECT COUNT(*) FROM events WHERE status='pending'").fetchone()[0]
        running = db.execute("SELECT COUNT(*) FROM sessions WHERE status='running'").fetchone()[0]
        tickets = db.execute("SELECT COUNT(*) FROM tickets WHERE status='open'").fetchone()[0]
        return {
            "db_path": str(harness_db_path()),
            "last_sync_at": get_last_sync_at(db),
            "pending_events": pending,
            "running_sessions": running,
            "open_tickets": tickets,
        }
    finally:
        db.close()
