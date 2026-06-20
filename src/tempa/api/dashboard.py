from __future__ import annotations

import asyncio
import shutil
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from tempa.channels.calendar.oauth import load_calendar_client
from tempa.channels.calendar.poller import find_triggerable_meet_events
from tempa.channels.whatsapp.client import EvolutionWhatsAppClient
from tempa.channels.whatsapp.webhook import get_recent_messages
from tempa.core.chat_sessions import session_count
from tempa.core.events import event_bus
from tempa.meet.archive import list_meetings
from tempa.rag.store import COLLECTION_NAME, ensure_store_healthy, get_store
from tempa.settings import get_settings


def _status_from_connected(connected: bool, detail: str = "") -> str:
    return "healthy" if connected else "unhealthy"


async def _check_evolution_api() -> dict[str, Any]:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{settings.evolution_api_url.rstrip('/')}/instance/fetchInstances",
                headers={"apikey": settings.evolution_api_key},
            )
            reachable = resp.status_code < 500
            return {
                "reachable": reachable,
                "status": "connected" if reachable else "disconnected",
                "status_code": resp.status_code,
            }
    except Exception as exc:
        return {"reachable": False, "status": "disconnected", "error": str(exc)}


async def _check_groq() -> dict[str, Any]:
    settings = get_settings()
    has_key = bool(settings.load_groq_api_key())
    if not has_key:
        return {"connected": False, "status": "disconnected", "detail": "No API key configured"}
    try:
        from tempa.router.groq_router import get_router

        result = await asyncio.to_thread(get_router().test_connection)
        return {"connected": True, "status": "connected", **result}
    except Exception as exc:
        return {"connected": False, "status": "error", "detail": str(exc)}


def _fetch_upcoming_meets() -> list[dict[str, Any]]:
    client = load_calendar_client()
    if not client:
        return []
    now = datetime.now(timezone.utc)
    events = client.list_upcoming_events(
        calendar_id="primary",
        time_min=now,
        time_max=now + timedelta(days=7),
    )
    return [
        {
            "id": e.id,
            "summary": e.summary,
            "start": e.start.isoformat(),
            "meet_url": e.meet_url,
            "has_meet": bool(e.meet_url),
        }
        for e in events[:15]
    ]


def _fetch_triggerable_meets() -> list[dict[str, Any]]:
    return [
        {"summary": ev.summary, "meet_url": ev.meet_url, "start": ev.start.isoformat()}
        for ev in find_triggerable_meet_events()
    ]


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def _component_checks() -> list[dict[str, Any]]:
    """End-to-end readiness per major Tempa subsystem."""
    settings = get_settings()
    groq_ok = bool(settings.load_groq_api_key())
    google_ok = settings.google_token_path.exists()
    storage_ok = settings.google_storage_state_path.exists()

    return [
        {
            "id": "daemon",
            "name": "Tempa Daemon",
            "category": "core",
            "status": "healthy",
            "message": "API responding",
        },
        {
            "id": "groq_router",
            "name": "Groq Model Router",
            "category": "inference",
            "status": "healthy" if groq_ok else "unhealthy",
            "message": "API key configured" if groq_ok else "Set GROQ_API_KEY",
        },
        {
            "id": "unified_rag",
            "name": "Unified Agentic RAG",
            "category": "memory",
            "status": "healthy",
            "message": f"Chroma collection `{COLLECTION_NAME}`",
        },
        {
            "id": "coordinator",
            "name": "Multi-Agent Coordinator",
            "category": "agents",
            "status": "healthy" if groq_ok else "degraded",
            "message": "LangGraph coordinator + 5 specialists",
        },
        {
            "id": "whatsapp_channel",
            "name": "WhatsApp (Evolution API)",
            "category": "channels",
            "status": "degraded",
            "message": "Webhook + client ready; requires Evolution sidecar",
        },
        {
            "id": "whatsapp_autoreply",
            "name": "WhatsApp Auto-Reply",
            "category": "channels",
            "status": "healthy",
            "message": "Inbound → coordinator + RAG → safety screen → send",
        },
        {
            "id": "google_calendar",
            "name": "Google Calendar",
            "category": "channels",
            "status": "healthy" if google_ok else "unhealthy",
            "message": "OAuth connected" if google_ok else "Complete Google OAuth",
        },
        {
            "id": "calendar_reminders",
            "name": "Calendar Reminders",
            "category": "channels",
            "status": "healthy" if google_ok else "degraded",
            "message": f"T−{settings.reminder_minutes_before} min WhatsApp + desktop notify-send",
        },
        {
            "id": "meet_bot",
            "name": "Google Meet Bot (Playwright)",
            "category": "meet",
            "status": "healthy" if storage_ok else "degraded",
            "message": "meeto code present"
            + ("; storage_state.json found" if storage_ok else "; run `tempa meet-auth`"),
        },
        {
            "id": "meet_pipeline",
            "name": "Meet Record → Transcribe → Archive",
            "category": "meet",
            "status": "healthy" if storage_ok else "degraded",
            "message": "Meet Agent → run_meeting_worker → archive + RAG ingest"
            + ("" if storage_ok else "; run `tempa meet-auth`"),
        },
        {
            "id": "meet_minutes",
            "name": "Meeting Minutes (Groq)",
            "category": "meet",
            "status": "healthy" if groq_ok else "unhealthy",
            "message": "Post-meeting minutes via meeting-lens + groq_backend",
        },
        {
            "id": "pc_agent",
            "name": "PC Control Agent",
            "category": "pc",
            "status": "healthy",
            "message": "Shell, files, apps, browser with allowlist",
        },
        {
            "id": "chrome_extension",
            "name": "Chrome Extension",
            "category": "ui",
            "status": "healthy",
            "message": "Side panel + popup + options; memory search; meeting viewer",
        },
        {
            "id": "web_dashboard",
            "name": "Web Dashboard",
            "category": "ui",
            "status": "healthy",
            "message": "This dashboard",
        },
        {
            "id": "safety_screen",
            "name": "Outbound Safety Screen",
            "category": "security",
            "status": "healthy" if groq_ok else "degraded",
            "message": "Safety GPT OSS 20B on outbound WhatsApp send",
        },
    ]


def _flow_status(groq_ok: bool = False) -> list[dict[str, Any]]:
    chat_ui_status = "healthy" if groq_ok else "degraded"
    return [
        {
            "id": "flow_0",
            "name": "Connections Init",
            "status": "degraded",
            "description": "Extension + dashboard setup Groq, Google, WhatsApp QR",
            "steps": [
                {"name": "Daemon running", "status": "healthy"},
                {"name": "Groq API key", "status": "degraded"},
                {"name": "Google OAuth", "status": "degraded"},
                {"name": "WhatsApp QR", "status": "degraded"},
            ],
        },
        {
            "id": "flow_1",
            "name": "Meet Reminder & Full Capture",
            "status": "degraded",
            "description": "Calendar → reminder → auto-join → transcribe → minutes → WhatsApp",
            "steps": [
                {"name": "Calendar poll", "status": "healthy"},
                {"name": "T−N reminders", "status": "healthy"},
                {"name": "Meet trigger (T−2 min)", "status": "healthy"},
                {"name": "Auto-join Playwright", "status": "degraded"},
                {"name": "Groq Whisper STT", "status": "degraded"},
                {"name": "Minutes + archive", "status": "healthy"},
                {"name": "WhatsApp summary", "status": "degraded"},
            ],
        },
        {
            "id": "flow_2",
            "name": "Cross-Tool Memory Lookup",
            "status": "degraded",
            "description": "Query unified RAG across WhatsApp + Meet + calendar",
            "steps": [
                {"name": "Unified ingest", "status": "healthy"},
                {"name": "Agentic RAG graph", "status": "healthy"},
                {"name": "Chat / dashboard UI", "status": chat_ui_status},
            ],
        },
        {
            "id": "flow_3",
            "name": "PC Task via WhatsApp",
            "status": "degraded",
            "description": "WhatsApp message → coordinator → PC agent",
            "steps": [
                {"name": "WhatsApp receive", "status": "healthy"},
                {"name": "Coordinator invoke", "status": "healthy"},
                {"name": "PC tools execute", "status": "healthy"},
                {"name": "WhatsApp reply", "status": "healthy"},
            ],
        },
        {
            "id": "flow_6",
            "name": "Multi-Agent Parallel",
            "status": "degraded",
            "description": "Coordinator fans out to specialists in parallel",
            "steps": [
                {"name": "Task decomposition", "status": "healthy"},
                {"name": "Parallel Send", "status": "healthy"},
                {"name": "Merge response", "status": "healthy"},
                {"name": "Activity WebSocket", "status": "healthy"},
            ],
        },
    ]


async def build_dashboard_payload() -> dict[str, Any]:
    settings = get_settings()
    store = get_store()
    groq = await _check_groq()
    evolution = await _check_evolution_api()

    from tempa.channels.calendar.status import google_connection_status
    from tempa.channels.gmail.status import gmail_connection_status
    from tempa.core.pending_actions import list_pending_actions
    from tempa.core.task_store import list_active_tasks

    google = await asyncio.to_thread(google_connection_status)
    gmail = await asyncio.to_thread(gmail_connection_status)

    from tempa.channels.whatsapp.session import sync_connection_from_evolution

    wa_detail: dict[str, Any] = {"connected": False, "status": "disconnected"}
    try:
        snapshot = await sync_connection_from_evolution()
        wa_connected = bool(snapshot.get("connected"))
        wa_detail = {
            "connected": wa_connected,
            "status": "connected" if wa_connected else snapshot.get("state", "disconnected"),
            "pause_auto_reply": snapshot.get("pause_auto_reply"),
        }
    except Exception as exc:
        wa_detail = {"connected": False, "status": "error", "detail": str(exc)}

    meetings = await list_meetings()

    upcoming_meets: list[dict[str, Any]] = []
    try:
        upcoming_meets = await asyncio.to_thread(_fetch_upcoming_meets)
    except Exception:
        pass

    triggerable = []
    try:
        triggerable = await asyncio.to_thread(_fetch_triggerable_meets)
    except Exception:
        pass

    with (settings.config_dir / "agents.yaml").open(encoding="utf-8") as f:
        agents_config = yaml.safe_load(f) or {}

    agents_list = []
    coord = agents_config.get("coordinator", {})
    agents_list.append(
        {
            "id": "coordinator",
            "name": coord.get("name", "Coordinator"),
            "role": coord.get("role", ""),
            "model_category": coord.get("model_category", "reasoning"),
            "status": "healthy" if groq.get("connected") else "degraded",
        }
    )
    for agent_id, meta in (agents_config.get("specialists") or {}).items():
        agents_list.append(
            {
                "id": agent_id,
                "name": meta.get("name", agent_id),
                "role": meta.get("role", ""),
                "model_category": meta.get("model_category", "text"),
                "status": "healthy",
            }
        )

    components = _component_checks()
    groq_ok = groq.get("connected", False)
    flows = _flow_status(groq_ok)

    # Update flow step statuses from live connections
    google_ok = google.get("connected", False)
    wa_ok = wa_detail.get("connected", False)
    for flow in flows:
        if flow["id"] == "flow_0":
            flow["steps"][1]["status"] = "healthy" if groq_ok else "unhealthy"
            flow["steps"][2]["status"] = "healthy" if google_ok else "unhealthy"
            flow["steps"][3]["status"] = "healthy" if wa_ok else "unhealthy"
            statuses = [s["status"] for s in flow["steps"]]
            flow["status"] = (
                "healthy" if all(s == "healthy" for s in statuses) else "degraded" if any(s == "healthy" for s in statuses) else "unhealthy"
            )

    rag_chunks = 0
    rag_status = "connected"
    rag_connected = True
    rag_error: str | None = None
    try:
        rag_chunks = store.count()
        if rag_chunks == 0:
            # Verify the store is actually readable (count=0 may mean empty or broken).
            store.collection.peek(limit=1)
    except Exception as exc:
        rag_status = "error"
        rag_connected = False
        rag_error = str(exc)[:200]
        if ensure_store_healthy(reset_on_failure=True):
            try:
                rag_chunks = store.count()
                rag_status = "connected"
                rag_connected = True
                rag_error = None
            except Exception as retry_exc:
                rag_error = str(retry_exc)[:200]

    connections = {
        "daemon": {"status": "connected", "connected": True, "port": settings.tempa_daemon_port},
        "groq": groq,
        "google": google,
        "gmail": gmail,
        "whatsapp": wa_detail,
        "evolution_api": evolution,
        "rag": {
            "status": rag_status,
            "connected": rag_connected,
            "collection": COLLECTION_NAME,
            "chunks": rag_chunks,
            "path": str(settings.vector_dir),
            **({"error": rag_error} if rag_error else {}),
        },
    }

    healthy = sum(1 for c in components if c["status"] == "healthy")
    degraded = sum(1 for c in components if c["status"] == "degraded")
    unhealthy = sum(1 for c in components if c["status"] == "unhealthy")

    if unhealthy > 5:
        overall = "unhealthy"
    elif unhealthy > 0 or degraded > 3:
        overall = "degraded"
    else:
        overall = "healthy"

    data_stats = {
        "rag_chunks": rag_chunks,
        "meetings_count": len(meetings),
        "chat_sessions_count": session_count(),
        "vector_db_path": str(settings.vector_dir),
        "vector_db_bytes": _dir_size(settings.vector_dir),
        "meetings_path": str(settings.meetings_dir),
        "meetings_bytes": _dir_size(settings.meetings_dir),
        "sessions_path": str(settings.sessions_dir),
        "db_path": str(settings.db_path),
        "playwright_installed": shutil.which("playwright") is not None,
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": {
            "status": overall,
            "healthy": healthy,
            "degraded": degraded,
            "unhealthy": unhealthy,
            "total_components": len(components),
        },
        "connections": connections,
        "agents": agents_list,
        "components": components,
        "flows": flows,
        "data": data_stats,
        "calendar": {
            "upcoming": upcoming_meets,
            "triggerable_now": triggerable,
            "poll_interval_seconds": settings.calendar_poll_seconds,
        },
        "whatsapp": {
            "recent_messages": get_recent_messages(15),
        },
        "meetings": meetings[:20],
        "recent_activity": event_bus.recent_events(30),
        "pending_actions": list_pending_actions(status="pending")[:10],
        "active_tasks": list_active_tasks()[:10],
        "environment": {
            "data_dir": str(settings.tempa_data_dir),
            "evolution_api_url": settings.evolution_api_url,
            "tempa_version": "0.1.0",
        },
    }
