from __future__ import annotations

import asyncio
import os
import shutil
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from tempa.channels.calendar.oauth import load_calendar_client
from tempa.channels.calendar.poller import find_triggerable_meet_events
from tempa.channels.whatsapp.client import WhatsAppBridgeClient
from tempa.channels.whatsapp.webhook import get_recent_messages
from tempa.core.chat_sessions import session_count
from tempa.core.events import event_bus
from tempa.meet.archive import list_meetings
from tempa.rag.store import COLLECTION_NAME, ensure_store_healthy, get_store
from tempa.settings import get_settings


def _status_from_connected(connected: bool, detail: str = "") -> str:
    return "healthy" if connected else "unhealthy"


async def _check_whatsapp_bridge() -> dict[str, Any]:
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


def _slack_component(slack: dict[str, Any], groq: dict[str, Any]) -> dict[str, Any]:
    configured = slack.get("configured", False)
    connected = slack.get("connected", False)
    owner_ok = slack.get("owner_configured", False)
    groq_ok = groq.get("connected", False)

    if connected and groq_ok and owner_ok:
        return {
            "id": "slack_channel",
            "name": "Slack",
            "category": "channels",
            "status": "healthy",
            "message": "Socket Mode connected; DMs + @mentions → coordinator",
            "action": None,
        }
    if connected and not owner_ok:
        return {
            "id": "slack_channel",
            "name": "Slack",
            "category": "channels",
            "status": "degraded",
            "message": "Connected — set SLACK_OWNER_USER_ID for DM auto-reply",
            "action": "/connections",
        }
    if configured and not connected:
        detail = slack.get("detail") or "Socket Mode not connected"
        return {
            "id": "slack_channel",
            "name": "Slack",
            "category": "channels",
            "status": "degraded",
            "message": detail,
            "action": "/connections",
        }
    return {
        "id": "slack_channel",
        "name": "Slack",
        "category": "channels",
        "status": "unhealthy",
        "message": "Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN in .env (optional channel)",
        "action": "/connections",
    }


def _whatsapp_bridge_component(
    bridge: dict[str, Any], whatsapp: dict[str, Any]
) -> dict[str, Any]:
    reachable = bridge.get("reachable", False)
    connected = whatsapp.get("connected", False)
    if connected and reachable:
        return {
            "id": "whatsapp_channel",
            "name": "WhatsApp Bridge",
            "category": "channels",
            "status": "healthy",
            "message": "Evolution bridge reachable; WhatsApp session connected",
            "action": "/connections",
        }
    if reachable and whatsapp.get("needs_qr_rescan"):
        return {
            "id": "whatsapp_channel",
            "name": "WhatsApp Bridge",
            "category": "channels",
            "status": "degraded",
            "message": "Bridge running — scan QR on Connections to reconnect WhatsApp",
            "action": "/connections",
        }
    if reachable:
        return {
            "id": "whatsapp_channel",
            "name": "WhatsApp Bridge",
            "category": "channels",
            "status": "degraded",
            "message": "Bridge reachable — connect WhatsApp on Connections",
            "action": "/connections",
        }
    detail = bridge.get("error") or (
        f"HTTP {bridge['status_code']}" if bridge.get("status_code") else ""
    )
    msg = "Start Evolution API sidecar (see README docker compose)"
    if detail:
        msg = f"{msg} — {detail}"
    return {
        "id": "whatsapp_channel",
        "name": "WhatsApp Bridge",
        "category": "channels",
        "status": "unhealthy",
        "message": msg,
        "action": "/connections",
    }


def _google_calendar_component(google: dict[str, Any]) -> dict[str, Any]:
    connected = google.get("connected", False)
    calendar_ok = google.get("calendar_api_ok", False)
    needs_reconnect = google.get("needs_reconnect", False)
    creds_ok = google.get("credentials_configured", False)

    if connected and calendar_ok:
        status = "healthy"
        message = "OAuth connected; Calendar API OK"
    elif needs_reconnect:
        status = "degraded"
        message = "Reconnect Google OAuth for calendar write access"
    elif connected and not calendar_ok:
        status = "degraded"
        message = google.get("detail") or "Calendar API check failed"
    elif creds_ok:
        status = "unhealthy"
        message = "Complete Google OAuth on Connections"
    else:
        status = "unhealthy"
        message = "Add Google credentials and complete OAuth"

    return {
        "id": "google_calendar",
        "name": "Google Calendar",
        "category": "channels",
        "status": status,
        "message": message,
        "action": "/connections" if status != "healthy" else None,
    }


def _calendar_reminders_component(
    google: dict[str, Any], whatsapp: dict[str, Any], *, minutes_before: int
) -> dict[str, Any]:
    google_ready = google.get("connected", False) and google.get("calendar_api_ok", False)
    wa_ready = whatsapp.get("connected", False)

    if google_ready and wa_ready:
        status = "healthy"
        message = f"T−{minutes_before} min WhatsApp + desktop notify-send"
    elif google_ready:
        status = "degraded"
        message = f"Calendar ready — connect WhatsApp for T−{minutes_before} min reminders"
    elif google.get("connected", False):
        status = "degraded"
        message = google.get("detail") or "Calendar API unavailable for reminders"
    else:
        status = "degraded"
        message = "Complete Google OAuth before reminders can run"

    action = None
    if status != "healthy":
        action = "/connections"

    return {
        "id": "calendar_reminders",
        "name": "Calendar Reminders",
        "category": "channels",
        "status": status,
        "message": message,
        "action": action,
    }


def _component_checks(
    *,
    groq: dict[str, Any],
    google: dict[str, Any],
    bridge: dict[str, Any],
    whatsapp: dict[str, Any],
    slack: dict[str, Any],
    rag_connected: bool = True,
    rag_error: str | None = None,
) -> list[dict[str, Any]]:
    """End-to-end readiness per major Tempa subsystem."""
    from tempa.security.sessions import secret_file_exists

    settings = get_settings()
    groq_ok = groq.get("connected", False)
    storage_ok = secret_file_exists("google/storage_state.json")
    wa_connected = whatsapp.get("connected", False)
    pause_reply = whatsapp.get("pause_auto_reply")

    if wa_connected and groq_ok and not pause_reply:
        autoreply_status = "healthy"
        autoreply_msg = "Inbound → coordinator + RAG → safety screen → send"
    elif wa_connected and pause_reply:
        autoreply_status = "degraded"
        autoreply_msg = "Auto-reply paused on Connections"
    elif bridge.get("reachable") and not wa_connected:
        autoreply_status = "degraded"
        autoreply_msg = "Connect WhatsApp before auto-reply can run"
    elif not groq_ok:
        autoreply_status = "degraded"
        autoreply_msg = "Configure Groq API key for auto-reply"
    else:
        autoreply_status = "unhealthy"
        autoreply_msg = "WhatsApp bridge unreachable"

    rag_status = "healthy" if rag_connected else "degraded"
    rag_msg = f"Chroma collection `{COLLECTION_NAME}`"
    if rag_error:
        rag_msg = f"{rag_msg} — {rag_error}"

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
            "status": rag_status,
            "message": rag_msg,
        },
        {
            "id": "coordinator",
            "name": "Multi-Agent Coordinator",
            "category": "agents",
            "status": "healthy" if groq_ok else "degraded",
            "message": "LangGraph coordinator + 5 specialists",
        },
        _whatsapp_bridge_component(bridge, whatsapp),
        _slack_component(slack, groq),
        {
            "id": "whatsapp_autoreply",
            "name": "WhatsApp Auto-Reply",
            "category": "channels",
            "status": autoreply_status,
            "message": autoreply_msg,
            "action": "/connections" if autoreply_status != "healthy" else None,
        },
        _google_calendar_component(google),
        _calendar_reminders_component(
            google, whatsapp, minutes_before=settings.reminder_minutes_before
        ),
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


def _aggregate_flow_status(steps: list[dict[str, Any]]) -> str:
    statuses = [str(s.get("status", "")).lower() for s in steps]
    if all(s == "healthy" for s in statuses):
        return "healthy"
    if any(s == "unhealthy" for s in statuses):
        return "degraded" if any(s == "healthy" for s in statuses) else "unhealthy"
    return "degraded"


def _step_status(ok: bool, *, soft: bool = False) -> str:
    if ok:
        return "healthy"
    return "degraded" if soft else "unhealthy"


def _flow_status(
    *,
    groq_ok: bool,
    google_ok: bool,
    wa_ok: bool,
    rag_connected: bool,
    meet_ready: bool,
    meet_worker_alive: bool,
    meet_delegate_to_worker: bool,
    meet_auto_join_enabled: bool,
    meet_auto_send_whatsapp: bool,
) -> list[dict[str, Any]]:
    auto_join_ok = meet_ready and (meet_worker_alive if meet_delegate_to_worker else True)

    flow_0_steps = [
        {"name": "Daemon running", "status": "healthy"},
        {"name": "Groq API key", "status": _step_status(groq_ok)},
        {"name": "Google OAuth", "status": _step_status(google_ok)},
        {"name": "WhatsApp QR", "status": _step_status(wa_ok)},
    ]

    flow_1_steps = [
        {"name": "Calendar poll", "status": _step_status(google_ok)},
        {"name": "T−N reminders", "status": _step_status(google_ok and wa_ok, soft=not wa_ok)},
        {"name": "Meet trigger (T−2 min)", "status": _step_status(google_ok and meet_auto_join_enabled)},
        {"name": "Auto-join Playwright", "status": _step_status(auto_join_ok, soft=not auto_join_ok)},
        {"name": "Groq Whisper STT", "status": _step_status(groq_ok)},
        {"name": "Minutes + archive", "status": _step_status(groq_ok and rag_connected, soft=not rag_connected)},
        {"name": "WhatsApp summary", "status": _step_status(wa_ok and meet_auto_send_whatsapp, soft=not wa_ok)},
    ]

    flow_2_steps = [
        {"name": "Unified ingest", "status": _step_status(rag_connected)},
        {"name": "Agentic RAG graph", "status": _step_status(rag_connected and groq_ok)},
        {"name": "Chat / dashboard UI", "status": _step_status(groq_ok)},
    ]

    flow_3_steps = [
        {"name": "WhatsApp receive", "status": _step_status(wa_ok)},
        {"name": "Coordinator invoke", "status": _step_status(groq_ok)},
        {"name": "PC tools execute", "status": "healthy"},
        {"name": "WhatsApp reply", "status": _step_status(wa_ok and groq_ok)},
    ]

    flow_6_steps = [
        {"name": "Task decomposition", "status": _step_status(groq_ok)},
        {"name": "Parallel Send", "status": _step_status(groq_ok)},
        {"name": "Merge response", "status": _step_status(groq_ok)},
        {"name": "Activity WebSocket", "status": "healthy"},
    ]

    flows = [
        {
            "id": "flow_0",
            "name": "Connections Init",
            "status": _aggregate_flow_status(flow_0_steps),
            "description": "Extension + dashboard setup Groq, Google, WhatsApp QR",
            "steps": flow_0_steps,
        },
        {
            "id": "flow_1",
            "name": "Meet Reminder & Full Capture",
            "status": _aggregate_flow_status(flow_1_steps),
            "description": "Calendar → reminder → auto-join → transcribe → minutes → WhatsApp",
            "steps": flow_1_steps,
        },
        {
            "id": "flow_2",
            "name": "Cross-Tool Memory Lookup",
            "status": _aggregate_flow_status(flow_2_steps),
            "description": "Query unified RAG across WhatsApp + Meet + calendar",
            "steps": flow_2_steps,
        },
        {
            "id": "flow_3",
            "name": "PC Task via WhatsApp",
            "status": _aggregate_flow_status(flow_3_steps),
            "description": "WhatsApp message → coordinator → PC agent",
            "steps": flow_3_steps,
        },
        {
            "id": "flow_6",
            "name": "Multi-Agent Parallel",
            "status": _aggregate_flow_status(flow_6_steps),
            "description": "Coordinator fans out to specialists in parallel",
            "steps": flow_6_steps,
        },
    ]
    return flows


async def build_dashboard_payload() -> dict[str, Any]:
    settings = get_settings()
    store = get_store()
    groq = await _check_groq()
    bridge = await _check_whatsapp_bridge()

    from tempa.channels.calendar.status import google_connection_status
    from tempa.channels.gmail.status import gmail_connection_status
    from tempa.core.pending_actions import list_pending_actions
    from tempa.core.task_store import list_active_tasks

    google = await asyncio.to_thread(google_connection_status)
    gmail = await asyncio.to_thread(gmail_connection_status)

    from tempa.channels.whatsapp.session import sync_connection_from_bridge

    wa_detail: dict[str, Any] = {"connected": False, "status": "disconnected"}
    try:
        snapshot = await sync_connection_from_bridge()
        wa_connected = bool(snapshot.get("connected"))
        wa_detail = {
            "connected": wa_connected,
            "status": "connected" if wa_connected else snapshot.get("state", "disconnected"),
            "pause_auto_reply": snapshot.get("pause_auto_reply"),
            "needs_qr_rescan": snapshot.get("needs_qr_rescan"),
        }
    except Exception as exc:
        wa_detail = {"connected": False, "status": "error", "detail": str(exc)}

    from tempa.channels.slack.session import connection_status

    slack_detail = await connection_status()

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

    groq_ok = groq.get("connected", False)
    google_ok = google.get("connected", False)
    wa_ok = wa_detail.get("connected", False)

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

    from tempa.meet.scheduler import meet_readiness
    from tempa.meet.worker_heartbeat import worker_is_alive

    meet_ready = meet_readiness()
    meet_delegate_to_worker = os.environ.get("TEMPA_MEET_DELEGATE_TO_WORKER", "").lower() in (
        "1",
        "true",
        "yes",
    )

    flows = _flow_status(
        groq_ok=groq_ok,
        google_ok=google_ok,
        wa_ok=wa_ok,
        rag_connected=rag_connected,
        meet_ready=meet_ready.ready,
        meet_worker_alive=worker_is_alive(),
        meet_delegate_to_worker=meet_delegate_to_worker,
        meet_auto_join_enabled=settings.meet_auto_join_enabled,
        meet_auto_send_whatsapp=settings.meet_auto_send_summary_whatsapp,
    )

    components = _component_checks(
        groq=groq,
        google=google,
        bridge=bridge,
        whatsapp=wa_detail,
        slack=slack_detail,
        rag_connected=rag_connected,
        rag_error=rag_error,
    )

    from tempa.core.sync_status import all_sync_status, get_sync_status

    sync_all = all_sync_status()
    gmail_sync = get_sync_status("gmail")
    calendar_sync = get_sync_status("calendar")
    slack_sync = get_sync_status("slack")
    if gmail_sync:
        gmail = {**gmail, **gmail_sync}
    if calendar_sync:
        google = {**google, "calendar_sync": calendar_sync}
    if slack_sync:
        slack_detail = {**slack_detail, **slack_sync}

    connections = {
        "daemon": {"status": "connected", "connected": True, "port": settings.tempa_daemon_port},
        "groq": groq,
        "google": google,
        "gmail": gmail,
        "whatsapp": wa_detail,
        "whatsapp_bridge": bridge,
        "slack": slack_detail,
        "evolution_api": bridge,
        "meet_auto_join": {
            "ready": meet_ready.ready,
            "connected": meet_ready.ready,
            "status": "connected" if meet_ready.ready else "degraded",
            "consent": meet_ready.consent,
            "meet_auth": meet_ready.meet_auth,
            "detail": meet_ready.detail,
        },
        "rag": {
            "status": rag_status,
            "connected": rag_connected,
            "collection": COLLECTION_NAME,
            "chunks": rag_chunks,
            "path": str(settings.vector_dir),
            **({"error": rag_error} if rag_error else {}),
        },
        "sync": sync_all,
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
            "whatsapp_bridge_url": settings.evolution_api_url,
            "evolution_api_url": settings.evolution_api_url,
            "tempa_version": "0.1.0",
        },
    }
