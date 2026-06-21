from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from tempa.api.dashboard import build_dashboard_payload
from tempa.channels.calendar.oauth import (
    authorization_url,
    begin_google_connect,
    disconnect_google,
    google_credentials_configured,
    handle_oauth_callback,
    save_google_credentials,
)
from tempa.channels.calendar.status import google_connection_status
from tempa.channels.gmail.oauth import (
    begin_gmail_connect,
    disconnect_gmail,
    handle_oauth_callback as handle_gmail_oauth_callback,
    is_gmail_oauth_state,
)
from tempa.channels.gmail.status import gmail_connection_status
from tempa.channels.calendar.poller import PollerState, load_poller_state, poll_once, save_poller_state
from tempa.channels.calendar.reminders import ReminderState, load_reminder_state, poll_reminders_once
from tempa.channels.whatsapp.client import WhatsAppBridgeClient
from tempa.channels.whatsapp.session import (
    get_connection_snapshot,
    mark_disconnected,
    needs_qr_rescan,
    parse_bridge_state,
    sync_connection_from_bridge,
    update_connection_state,
)
from tempa.channels.whatsapp.webhook import handle_webhook
from tempa.api.settings_store import apply_daemon_settings, get_public_settings, save_daemon_settings
from tempa.core.events import event_bus
from tempa.meet.archive import delete_meeting, erase_all_user_data, export_user_data, get_meeting, init_db, list_meetings, read_live_meeting_state, apply_meet_retention_policy
from tempa.meet.consent import grant_recording_consent, has_recording_consent, revoke_recording_consent
from tempa.meet.service import get_active_meeting_ids, get_meeting_jobs, schedule_meeting_join_async
from tempa.meet.scheduler import meet_readiness
from tempa.meet.session_registry import list_active_sessions
from tempa.rag.ingest import ingest_text, search_memory
from tempa.rag.store import get_store
from tempa.router.groq_router import get_router
from tempa.settings import get_settings


class GroqConnectionRequest(BaseModel):
    api_key: str


class GoogleCredentialsRequest(BaseModel):
    client_id: str
    client_secret: str


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None


class MemorySearchRequest(BaseModel):
    query: str
    top_k: int = 5
    tool: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    participant: str | None = None
    tags: list[str] | None = None


class PreferenceRequest(BaseModel):
    rule: str
    source: str = "manual"
    tags: list[str] = Field(default_factory=list)


class DaemonSettingsRequest(BaseModel):
    reminder_minutes_before: int | None = None
    meet_auto_join_on_reminder: bool | None = None
    meet_auto_join_enabled: bool | None = None
    meet_trigger_before_minutes: int | None = None
    meet_trigger_after_start_minutes: int | None = None
    meet_skip_keywords: list[str] | None = None
    meet_retention_days: int | None = None
    meet_auto_send_summary_whatsapp: bool | None = None
    meet_copilot_whatsapp_notify: bool | None = None


class MeetingJoinRequest(BaseModel):
    meet_url: str
    title: str = ""
    notify_number: str | None = None


class MeetingChatRequest(BaseModel):
    text: str


class WhatsAppAllowedNumbersRequest(BaseModel):
    additional_numbers: list[str] = Field(default_factory=list)


_poller_state = load_poller_state()
reminder_state = load_reminder_state()
_scheduler_task: asyncio.Task | None = None
_reminder_task: asyncio.Task | None = None
_gmail_sync_task: asyncio.Task | None = None
_consolidation_task: asyncio.Task | None = None
_retention_task: asyncio.Task | None = None
_shutdown_requested = False


async def _gmail_sync_loop() -> None:
    from tempa.channels.gmail.sync import sync_once

    settings = get_settings()
    try:
        import yaml

        with (settings.config_dir / "permissions.yaml").open(encoding="utf-8") as f:
            cfg = (yaml.safe_load(f) or {}).get("gmail") or {}
        interval = int(cfg.get("poll_interval_seconds", 120))
        sync_on_startup = bool(cfg.get("sync_on_startup", True))
    except Exception:
        interval = 120
        sync_on_startup = True

    if sync_on_startup:
        async def _startup_sync() -> None:
            try:
                await sync_once(full=False)
            except Exception:
                pass

        asyncio.create_task(_startup_sync())
    while True:
        await asyncio.sleep(interval)
        try:
            await sync_once(full=False)
        except Exception:
            pass


async def _calendar_loop() -> None:
    import logging

    from tempa.meet.scheduler import schedule_join_for_calendar_event

    logger = logging.getLogger(__name__)

    async def on_trigger(ev):
        await schedule_join_for_calendar_event(ev)

    settings = get_settings()
    while True:
        try:
            triggered = await poll_once(_poller_state, on_trigger)
            if triggered:
                logger.info("Calendar poller queued %s meet join(s)", len(triggered))
        except Exception:
            logger.exception("Calendar poller error")
        await asyncio.sleep(settings.calendar_poll_seconds)


async def _reminder_loop() -> None:
    settings = get_settings()
    while True:
        try:
            await poll_reminders_once(reminder_state)
        except Exception:
            pass
        await asyncio.sleep(max(30, settings.calendar_poll_seconds))


async def _retention_loop() -> None:
    while True:
        await asyncio.sleep(24 * 3600)
        try:
            removed = await apply_meet_retention_policy()
            if removed:
                import logging

                logging.getLogger(__name__).info("Meet retention removed %s archives", removed)
        except Exception:
            pass


async def _consolidation_loop() -> None:
    while True:
        await asyncio.sleep(24 * 3600)
        try:
            from tempa.rag.consolidation import run_consolidation

            await asyncio.to_thread(run_consolidation)
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler_task, _reminder_task, _gmail_sync_task, _consolidation_task, _retention_task
    from tempa.channels.contacts.store import init_contacts_db
    from tempa.channels.whatsapp.inbound_queue import stop_inbound_worker
    from tempa.channels.whatsapp.webhook import ensure_webhook_worker
    from tempa.core.runtime import set_main_loop
    from tempa.core.task_store import sweep_stale_tasks
    from tempa.security.sessions import decrypt_sensitive_sessions, encrypt_sensitive_sessions

    settings = get_settings()
    settings.ensure_dirs()
    set_main_loop(asyncio.get_running_loop())
    decrypt_sensitive_sessions()
    apply_daemon_settings()
    from tempa.plugins.registry import load_builtin_plugins

    load_builtin_plugins()
    await init_db()
    await init_contacts_db()
    sweep_stale_tasks()

    def _warm_embedder() -> None:
        from tempa.rag.embeddings import get_embedder

        get_embedder().embed("tempa warmup")

    await asyncio.to_thread(_warm_embedder)
    await ensure_webhook_worker()

    async def _whatsapp_startup() -> None:
        from tempa.channels.whatsapp.qr_tasks import auto_manage_connection

        try:
            client = WhatsAppBridgeClient()
            webhook_base = settings.tempa_webhook_base_url.strip() or (
                f"http://127.0.0.1:{settings.tempa_daemon_port}"
            )
            webhook_url = f"{webhook_base.rstrip('/')}/webhooks/whatsapp"
            await client.startup_sync(webhook_url)
            state_name, connected = await client.resolved_connection_state()
            if not connected:
                await auto_manage_connection()
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("WhatsApp startup failed: %s", exc)

    asyncio.create_task(_whatsapp_startup())

    async def _deferred_background() -> None:
        global _scheduler_task, _reminder_task, _gmail_sync_task, _consolidation_task, _retention_task
        await asyncio.sleep(2)
        _scheduler_task = asyncio.create_task(_calendar_loop())
        _reminder_task = asyncio.create_task(_reminder_loop())
        _gmail_sync_task = asyncio.create_task(_gmail_sync_loop())
        _consolidation_task = asyncio.create_task(_consolidation_loop())
        _retention_task = asyncio.create_task(_retention_loop())
        try:
            from tempa.channels.contacts.sync import sync_contacts

            asyncio.create_task(sync_contacts())
        except Exception:
            pass
        try:
            from tempa.pc.transfer.server import ensure_transfer_server

            asyncio.create_task(ensure_transfer_server())
        except Exception:
            pass

    asyncio.create_task(_deferred_background())
    yield
    if _scheduler_task:
        _scheduler_task.cancel()
    if _reminder_task:
        _reminder_task.cancel()
    if _gmail_sync_task:
        _gmail_sync_task.cancel()
    try:
        from tempa.pc.transfer.server import stop_transfer_server

        await stop_transfer_server()
    except Exception:
        pass
    await stop_inbound_worker()
    encrypt_sensitive_sessions()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Tempa Daemon", version="0.1.0", lifespan=lifespan)
    from tempa.api.features import router as features_router

    app.include_router(features_router, prefix="/api")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.tempa_cors_origin] if settings.tempa_cors_origin != "*" else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/dashboard")
    async def dashboard_status():
        return await build_dashboard_payload()

    @app.get("/api/health")
    async def health():
        import os

        components: dict[str, Any] = {}

        def _chromadb_check() -> dict[str, Any]:
            try:
                count = get_store().count()
                return {"status": "ok", "chunks": count}
            except Exception as exc:
                return {"status": "error", "error": str(exc)[:200]}

        def _groq_check() -> dict[str, Any]:
            if not settings.load_groq_api_key():
                return {"status": "disconnected", "connected": False}
            try:
                result = get_router().test_connection()
                return {"status": "ok", "connected": True, **result}
            except Exception as exc:
                return {"status": "degraded", "connected": False, "error": str(exc)[:200]}

        def _meet_worker_check() -> dict[str, Any]:
            delegate = os.environ.get("TEMPA_MEET_DELEGATE_TO_WORKER", "").lower() in ("1", "true", "yes")
            jobs = get_meeting_jobs()
            queued = sum(1 for j in jobs.values() if j.get("status") == "queued")
            running = sum(1 for j in jobs.values() if j.get("status") in ("running", "finalizing"))
            mode = "delegated" if delegate else "in_process"
            return {"status": "ok", "mode": mode, "queued": queued, "running": running}

        chroma, groq, meet_worker = await asyncio.gather(
            asyncio.to_thread(_chromadb_check),
            asyncio.to_thread(_groq_check),
            asyncio.to_thread(_meet_worker_check),
        )
        components["chromadb"] = chroma
        components["groq"] = groq
        components["meet_worker"] = meet_worker

        overall = "ok"
        if chroma.get("status") == "error" or groq.get("status") == "degraded":
            overall = "degraded"

        return {
            "status": overall,
            "daemon": "tempa",
            "port": settings.tempa_daemon_port,
            "rag_chunks": chroma.get("chunks", 0),
            "components": components,
        }

    @app.get("/api/connections")
    async def connections():
        groq_ok = bool(settings.load_groq_api_key())
        google = await asyncio.to_thread(google_connection_status)
        gmail = await asyncio.to_thread(gmail_connection_status)
        wa_client = WhatsAppBridgeClient()
        try:
            wa_snapshot = await sync_connection_from_bridge()
            wa_connected = bool(wa_snapshot.get("connected"))
        except Exception:
            wa_connected = False
        return {
            "daemon": {"status": "connected", "connected": True},
            "groq": {"status": "connected" if groq_ok else "disconnected", "connected": groq_ok},
            "google": google,
            "gmail": gmail,
            "whatsapp": {
                "status": "connected" if wa_connected else "disconnected",
                "connected": wa_connected,
                "needs_qr_rescan": needs_qr_rescan() or not wa_connected,
                **get_connection_snapshot(),
            },
            "rag": {"status": "connected", "connected": True, "chunks": get_store().count()},
        }

    @app.post("/api/connections/groq")
    async def connect_groq(body: GroqConnectionRequest):
        from tempa.security.sessions import write_secret_file

        write_secret_file("groq.key", body.api_key.strip())
        settings.groq_api_key = body.api_key.strip()
        from tempa.router import groq_router as gr

        gr._router = None
        result = await asyncio.to_thread(get_router().test_connection)
        return {"status": "connected", **result}

    @app.get("/api/connections/groq/models")
    async def groq_models():
        router = get_router()
        return {
            "chains": {cat: router.chain_for(cat) for cat in router._chains},
            "categories": list(router._chains.keys()),
        }

    @app.get("/api/plugins")
    async def list_plugins():
        from tempa.plugins.registry import list_tools

        return {"tools": list_tools()}

    @app.post("/api/connections/google/credentials")
    async def save_google_oauth_credentials(body: GoogleCredentialsRequest):
        save_google_credentials(body.client_id, body.client_secret)
        return {
            "status": "saved",
            "credentials_configured": google_credentials_configured(),
        }

    @app.post("/api/connections/google")
    async def connect_google():
        if not google_credentials_configured():
            return {
                "status": "error",
                "detail": "Google OAuth credentials not configured. Save client ID and secret first.",
            }
        return {"authorization_url": begin_google_connect()}

    @app.delete("/api/connections/google")
    async def disconnect_google_account():
        disconnect_google()
        return {"status": "disconnected", "connected": False}

    @app.get("/api/connections/google/callback")
    async def google_callback(code: str, state: str):
        is_gmail = is_gmail_oauth_state(state)
        try:
            if is_gmail:
                handle_gmail_oauth_callback(code, state)
                title = "Gmail connected"
                msg_type = "tempa-gmail-oauth"
            else:
                handle_oauth_callback(code, state)
                title = "Google Calendar connected"
                msg_type = "tempa-google-oauth"
            return HTMLResponse(
                f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Tempa — {title}</title>
<link rel="stylesheet" href="https://fonts.cdnfonts.com/css/futura-pt">
<style>
body{{font-family:'Futura PT',Futura,'Century Gothic',sans-serif;max-width:32rem;margin:4rem auto;text-align:center;
background:#060d18;color:#fff;letter-spacing:.03em}}
.ok{{color:#3d6cb9;font-size:3rem}}h1{{font-weight:500}}p{{color:#b8c4d9}}</style></head>
<body><div class="ok">✓</div><h1>{title}</h1>
<p>You can close this tab and return to the Tempa dashboard.</p>
<script>
if (window.opener) {{
  window.opener.postMessage({{ type: "{msg_type}", status: "success" }}, window.location.origin);
  setTimeout(function () {{ window.close(); }}, 1200);
}}
</script></body></html>"""
            )
        except Exception as exc:
            msg_type = "tempa-gmail-oauth" if is_gmail else "tempa-google-oauth"
            return HTMLResponse(
                f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.cdnfonts.com/css/futura-pt">
<style>body{{font-family:'Futura PT',Futura,sans-serif;background:#060d18;color:#fff;padding:2rem}}</style></head>
<body><h1>Google connection failed</h1><p style="color:#b8c4d9">{exc}</p>
<script>
if (window.opener) {{
  window.opener.postMessage({{ type: "{msg_type}", status: "error", detail: {json.dumps(str(exc))} }}, window.location.origin);
}}
</script></body></html>""",
                status_code=400,
            )

    @app.post("/api/connections/gmail")
    async def connect_gmail():
        if not google_credentials_configured():
            return {
                "status": "error",
                "detail": "Google OAuth credentials not configured. Save client ID and secret first.",
            }
        return {"authorization_url": begin_gmail_connect()}

    @app.delete("/api/connections/gmail")
    async def disconnect_gmail_account():
        disconnect_gmail()
        return {"status": "disconnected", "connected": False}

    @app.get("/api/connections/gmail/callback")
    async def gmail_callback(code: str, state: str):
        """Legacy path — Gmail OAuth now uses the shared Google callback."""
        return await google_callback(code, state)

    @app.get("/api/connections/whatsapp")
    async def whatsapp_status(qr: bool = False, refresh: bool = False):
        import logging
        import time as _time

        from tempa.channels.whatsapp.qr_tasks import auto_manage_connection, last_qr_error, qr_task_running, schedule_fetch_qr
        from tempa.channels.whatsapp.session import get_qr_code
        from tempa.debug_agent_log import agent_log

        log = logging.getLogger(__name__)
        _t0 = _time.monotonic()
        client = WhatsAppBridgeClient()
        try:
            state_name, connected = await client.resolved_connection_state()
            # #region agent log
            agent_log(
                location="app.py:whatsapp_status:state",
                message="status poll state",
                data={"qr": qr, "refresh": refresh, "state_name": state_name, "connected": connected},
                hypothesis_id="H1",
            )
            # #endregion
            snapshot = update_connection_state(state_name)
            connected = bool(snapshot.get("connected"))
            result: dict[str, Any] = {
                "connection_state": {"instance": {"instanceName": client.instance, "state": state_name}},
                "connected": connected,
                "status": state_name,
                "needs_qr_rescan": needs_qr_rescan() or not connected,
                "qr_code": None,
                **snapshot,
            }
            if qr and not connected:
                if refresh:
                    if state_name == "connecting":
                        synced = await client.read_cached_qr()
                        if synced:
                            result["qr_code"] = synced
                            result["status"] = "connecting"
                            result["auto_action"] = "connecting"
                        else:
                            result["detail"] = "Pairing in progress — fetching QR from bridge"
                            result["auto_action"] = "connecting"
                            if not qr_task_running():
                                await schedule_fetch_qr(refresh=False)
                    else:
                        await schedule_fetch_qr(refresh=True)
                        result["auto_action"] = "refresh"
                        result["detail"] = "Fetching new QR — check back in a few seconds"
                else:
                    managed = await auto_manage_connection()
                    result["auto_action"] = managed.get("action")
                    if managed.get("qr_code"):
                        result["qr_code"] = managed["qr_code"]
                        result["status"] = "connecting"
                    if managed.get("detail"):
                        result["detail"] = managed["detail"]
                        if managed.get("action") == "error" or "failed" in str(managed["detail"]).lower():
                            result["status"] = "error"
                cached = get_qr_code()
                if not cached and state_name == "connecting":
                    synced = await client.read_cached_qr()
                    if synced:
                        cached = synced
                        result["qr_code"] = synced
                        result["status"] = "connecting"
                        result.pop("detail", None)
                if cached and state_name == "connecting":
                    result["qr_code"] = cached
                    result["status"] = "connecting"
                    result.pop("detail", None)
                elif cached and state_name in {"close", "disconnected", "refused"}:
                    result["qr_code"] = cached
                    result["status"] = "connecting"
                    result.pop("detail", None)
                elif cached:
                    result["qr_code"] = cached
                elif not result.get("detail"):
                    err = last_qr_error()
                    if state_name in {"close", "disconnected", "refused"}:
                        result["status"] = state_name
                    elif result.get("status") != "error":
                        result["status"] = "connecting"
                    if err and qr_task_running():
                        result["detail"] = err
                    elif err and state_name in {"close", "disconnected", "refused"}:
                        result["detail"] = err
                        result["status"] = "error" if "failed" in err.lower() else state_name
                    else:
                        result["detail"] = err or (
                            "Fetching QR from bridge…"
                            if qr_task_running()
                            else "Click Refresh QR to generate a new code"
                        )
                    if err:
                        log.warning("WhatsApp QR poll: %s", err)
            # #region agent log
            agent_log(
                location="app.py:whatsapp_status:exit",
                message="status response",
                data={
                    "status": result.get("status"),
                    "state_name": state_name,
                    "connected": result.get("connected"),
                    "qr_len": len(result.get("qr_code") or ""),
                    "refresh": refresh,
                    "elapsed_ms": int((_time.monotonic() - _t0) * 1000),
                    "auto_action": result.get("auto_action"),
                    "detail": (result.get("detail") or "")[:80],
                    "qr_task_running": qr_task_running(),
                },
                hypothesis_id="H1",
            )
            # #endregion
            return result
        except Exception as exc:
            log.exception("WhatsApp status failed")
            return {
                "status": "error",
                "detail": str(exc),
                "qr_code": None,
                "connected": False,
                "needs_qr_rescan": True,
            }

    @app.post("/api/connections/whatsapp/connect")
    async def whatsapp_connect():
        from tempa.channels.whatsapp.qr_tasks import schedule_fetch_qr
        from tempa.channels.whatsapp.session import get_qr_code, update_connection_state as _update

        client = WhatsAppBridgeClient()
        try:
            state_name, connected = await client.resolved_connection_state()
            if connected:
                _update("open")
                return {
                    "status": "open",
                    "qr_code": None,
                    "connected": True,
                    "needs_qr_rescan": False,
                }
            await schedule_fetch_qr(refresh=True)
            cached = get_qr_code()
            return {
                "status": "connecting",
                "qr_code": cached,
                "connected": False,
                "needs_qr_rescan": True,
                "detail": "Generating QR — refresh if it does not appear" if not cached else None,
            }
        except Exception as exc:
            return {"status": "error", "detail": str(exc), "qr_code": None, "connected": False}

    @app.post("/api/connections/whatsapp/restart")
    async def whatsapp_restart():
        """Reset WhatsApp bridge instance when stuck on connecting (401 / stale session)."""
        from tempa.channels.whatsapp.qr_tasks import schedule_restart
        from tempa.channels.whatsapp.session import get_qr_code

        settings = get_settings()
        webhook_base = settings.tempa_webhook_base_url.strip() or (
            f"http://host.docker.internal:{settings.tempa_daemon_port}"
        )
        webhook_url = f"{webhook_base.rstrip('/')}/webhooks/whatsapp"
        try:
            await schedule_restart(webhook_url)
            cached = get_qr_code()
            return {
                "status": "connecting",
                "qr_code": cached,
                "connected": False,
                "needs_qr_rescan": True,
                "detail": "Session reset started — poll for QR or click Refresh QR",
            }
        except Exception as exc:
            return {"status": "error", "detail": str(exc), "qr_code": None, "connected": False}

    @app.delete("/api/connections/whatsapp")
    async def whatsapp_disconnect():
        client = WhatsAppBridgeClient()
        try:
            result = await client.logout()
        except Exception as exc:
            return {"status": "error", "detail": str(exc), "connected": False}
        snapshot = mark_disconnected()
        return {
            "status": "disconnected",
            "connected": False,
            "needs_qr_rescan": True,
            "bridge": result,
            "connection_state": snapshot,
        }

    @app.get("/api/connections/whatsapp/allowed-numbers")
    async def whatsapp_allowed_numbers_get():
        from tempa.channels.whatsapp.numbers import (
            get_allowed_whatsapp_reply_numbers,
            get_extra_allowed_whatsapp_numbers,
            get_owner_whatsapp_number,
        )

        primary = get_owner_whatsapp_number()
        extra = get_extra_allowed_whatsapp_numbers()
        return {
            "primary_number": primary or None,
            "additional_numbers": extra,
            "allowed_numbers": get_allowed_whatsapp_reply_numbers(),
        }

    @app.put("/api/connections/whatsapp/allowed-numbers")
    async def whatsapp_allowed_numbers_put(body: WhatsAppAllowedNumbersRequest):
        from tempa.channels.whatsapp.numbers import (
            get_allowed_whatsapp_reply_numbers,
            get_owner_whatsapp_number,
            set_extra_allowed_whatsapp_numbers,
        )

        extra = set_extra_allowed_whatsapp_numbers(body.additional_numbers)
        return {
            "primary_number": get_owner_whatsapp_number() or None,
            "additional_numbers": extra,
            "allowed_numbers": get_allowed_whatsapp_reply_numbers(),
        }

    @app.post("/api/chat/runs/{run_id}/cancel")
    async def cancel_chat_run(run_id: str):
        from fastapi import HTTPException

        from tempa.core.chat_runs import cancel_run

        if not await cancel_run(run_id):
            raise HTTPException(status_code=404, detail="run_not_found")
        return {"status": "cancelled", "run_id": run_id}

    @app.post("/api/chat")
    async def chat(body: ChatRequest):
        import uuid

        from tempa.agents.graph import run_coordinator_streaming
        from tempa.core.chat_runs import register_run, unregister_run
        from tempa.core.chat_sessions import append_message, ensure_session
        from tempa.core.events import event_bus

        run_id = body.run_id or str(uuid.uuid4())

        async def event_generator():
            queue: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()
            done = asyncio.Event()
            cancel_event = await register_run(run_id)

            session = ensure_session(body.session_id)
            session_id = session["id"]
            append_message(session_id, "user", body.message)
            await queue.put(("run_started", {"run_id": run_id, "session_id": session_id}))

            async def on_token(delta: str) -> None:
                await queue.put(("token", {"delta": delta}))

            async def activity_forwarder() -> None:
                sub = await event_bus.subscribe()
                try:
                    while not done.is_set():
                        try:
                            event = await asyncio.wait_for(sub.get(), timeout=0.15)
                            if event.get("event_kind") == "step":
                                await queue.put(("step", event))
                            else:
                                await queue.put(("activity", event))
                        except asyncio.TimeoutError:
                            continue
                finally:
                    await event_bus.unsubscribe(sub)

            async def run_coordinator() -> None:
                try:
                    chat_context = dict(body.context)
                    chat_context["session_id"] = session_id
                    chat_context.setdefault("channel", "dashboard")
                    chat_context["cancel_event"] = cancel_event
                    chat_context["run_id"] = run_id
                    result = await run_coordinator_streaming(
                        body.message,
                        chat_context,
                        on_token=on_token,
                    )
                    content = result.get("response", "")
                    sources = result.get("sources") or []
                    paused = bool(result.get("paused"))
                    pending_actions = result.get("pending_actions") or []
                    artifacts = result.get("artifacts") or []
                    if content:
                        append_message(
                            session_id,
                            "assistant",
                            content,
                            sources=sources,
                            paused=paused,
                        )
                    await queue.put(
                        (
                            "message",
                            {
                                "content": content,
                                "sources": sources,
                                "paused": paused,
                                "session_id": session_id,
                                "pending_actions": pending_actions,
                                "artifacts": artifacts,
                                "run_id": run_id,
                            },
                        )
                    )
                except asyncio.CancelledError:
                    await queue.put(("error", {"error": "Run cancelled"}))
                except Exception as exc:
                    await queue.put(("error", {"error": str(exc)}))
                finally:
                    done.set()
                    await queue.put(None)

            forwarder = asyncio.create_task(activity_forwarder())
            runner = asyncio.create_task(run_coordinator())

            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        yield {"event": "done", "data": "{}"}
                        break
                    kind, data = item
                    yield {"event": kind, "data": json.dumps(data)}
            finally:
                done.set()
                forwarder.cancel()
                runner.cancel()
                await unregister_run(run_id)
                for task in (forwarder, runner):
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        return EventSourceResponse(event_generator())

    @app.post("/api/memory/search")
    async def memory_search(body: MemorySearchRequest):
        from tempa.rag.filters import extract_filters_from_query

        filters = extract_filters_from_query(body.query)
        return {
            "results": search_memory(
                body.query,
                top_k=body.top_k,
                tool=body.tool or filters.get("tool"),
                date_from=body.date_from or filters.get("date_from"),
                date_to=body.date_to or filters.get("date_to"),
                participant=body.participant or filters.get("participant"),
                tags=body.tags or filters.get("tags"),
            )
        }

    @app.get("/api/memory/preferences")
    async def memory_preferences_list():
        from tempa.rag.procedural import list_preferences

        return {"preferences": list_preferences()}

    @app.post("/api/memory/preferences")
    async def memory_preferences_add(body: PreferenceRequest):
        from tempa.rag.procedural import add_preference

        return add_preference(body.rule, source=body.source, tags=body.tags)

    @app.delete("/api/memory/preferences/{pref_id}")
    async def memory_preferences_delete(pref_id: str):
        from tempa.rag.procedural import delete_preference

        if not delete_preference(pref_id):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="not_found")
        return {"deleted": True}

    @app.get("/api/meetings")
    async def meetings():
        return {"meetings": await list_meetings(), "jobs": get_meeting_jobs()}

    @app.post("/api/meetings/join")
    async def meeting_join(body: MeetingJoinRequest):
        meet_url = body.meet_url.strip()
        if "meet.google.com" not in meet_url:
            return {"status": "error", "detail": "Invalid Google Meet URL"}
        try:
            meeting_id = await schedule_meeting_join_async(
                meet_url,
                title=body.title,
                notify_number=body.notify_number,
            )
            return {"status": "queued", "meeting_id": meeting_id, "meet_url": meet_url}
        except RuntimeError as exc:
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/meetings/consent")
    async def meet_consent_status():
        return {"consented": has_recording_consent()}

    @app.post("/api/meetings/consent")
    async def meet_consent_grant():
        return grant_recording_consent()

    @app.delete("/api/meetings/consent")
    async def meet_consent_revoke():
        return revoke_recording_consent()

    @app.get("/api/meetings/readiness")
    async def meetings_readiness():
        r = meet_readiness()
        return {
            "ready": r.ready,
            "consent": r.consent,
            "meet_auth": r.meet_auth,
            "google_connected": r.google_connected,
            "detail": r.detail,
        }

    @app.get("/api/meetings/active")
    async def meetings_active():
        jobs = get_meeting_jobs()
        active_ids = get_active_meeting_ids()
        sessions = list_active_sessions()
        live: list[dict[str, Any]] = []
        for mid in active_ids:
            row = jobs.get(mid, {})
            live.append(
                {
                    "meeting_id": mid,
                    "title": row.get("title", ""),
                    "meet_url": row.get("meet_url", ""),
                    "status": row.get("status", "unknown"),
                    **read_live_meeting_state(mid),
                }
            )
        return {"active": live, "sessions": sessions}

    @app.get("/api/meetings/{meeting_id}/live")
    async def meeting_live(meeting_id: str):
        jobs = get_meeting_jobs()
        if meeting_id not in jobs and not list_active_sessions():
            meeting = await get_meeting(meeting_id)
            if not meeting:
                return {"error": "not_found"}
        return read_live_meeting_state(meeting_id)

    @app.post("/api/meetings/{meeting_id}/chat")
    async def meeting_chat(meeting_id: str, body: MeetingChatRequest):
        from tempa.meet.copilot import send_meeting_chat

        text = body.text.strip()
        if not text:
            return {"status": "error", "detail": "empty message"}
        ok = await send_meeting_chat(meeting_id, text)
        if not ok:
            return {"status": "error", "detail": "no active session or send failed"}
        return {"status": "sent", "meeting_id": meeting_id}

    @app.websocket("/api/meetings/{meeting_id}/stream")
    async def meeting_stream(websocket: WebSocket, meeting_id: str):
        await websocket.accept()
        last_suggestions = 0
        try:
            while True:
                state = read_live_meeting_state(meeting_id)
                suggestions = state.get("suggestions") or []
                if len(suggestions) != last_suggestions:
                    await websocket.send_json({"type": "live", **state})
                    last_suggestions = len(suggestions)
                else:
                    await websocket.send_json(
                        {
                            "type": "heartbeat",
                            "transcript_tail": state.get("transcript_tail", ""),
                            "live_notes": state.get("live_notes", ""),
                        }
                    )
                await asyncio.sleep(3)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    @app.get("/api/meetings/{meeting_id}")
    async def meeting_detail(meeting_id: str):
        from tempa.core.pending_actions import list_pending_actions

        meeting = await get_meeting(meeting_id)
        if not meeting:
            return {"error": "not_found"}
        transcript = ""
        path = meeting.get("transcript_path")
        if path:
            from pathlib import Path

            p = Path(path)
            if p.exists():
                transcript = p.read_text(encoding="utf-8")
        pending = [
            a
            for a in list_pending_actions(status="pending")
            if (a.get("source_channel") or "").startswith(f"meeting:{meeting_id}")
        ]
        return {"meeting": meeting, "transcript_raw": transcript, "pending_followups": pending}

    @app.get("/api/meetings/{meeting_id}/audio")
    async def meeting_audio(meeting_id: str):
        from pathlib import Path

        from tempa.meet.audio_convert import resolve_audio_path

        meeting = await get_meeting(meeting_id)
        if not meeting:
            return {"error": "not_found"}
        safe_id = meeting_id.replace("/", "_").replace("\\", "_")
        path: Path | None = None
        audio_path = meeting.get("audio_path")
        if audio_path:
            candidate = Path(audio_path)
            if candidate.exists():
                path = candidate
        if path is None:
            path = resolve_audio_path(settings.meetings_dir / safe_id, safe_id)
        if not path or not path.exists():
            return {"error": "audio_not_found"}
        media = "audio/wav" if str(path).endswith(".wav") else "audio/pcm"
        return FileResponse(path, media_type=media, filename=path.name)

    @app.delete("/api/meetings/{meeting_id}")
    async def meeting_delete(meeting_id: str):
        ok = await delete_meeting(meeting_id)
        return {"deleted": ok}

    @app.get("/api/export")
    async def export_data():
        return await export_user_data()

    @app.post("/api/erasure")
    async def erasure():
        return await erase_all_user_data()

    @app.get("/api/settings")
    async def daemon_settings_get():
        return get_public_settings()

    @app.post("/api/settings")
    async def daemon_settings_post(body: DaemonSettingsRequest):
        saved = save_daemon_settings(body.model_dump(exclude_none=True))
        apply_daemon_settings()
        return {"saved": saved, **get_public_settings()}

    @app.post("/api/daemon/restart")
    async def daemon_restart():
        import subprocess
        import sys

        subprocess.Popen(
            [sys.executable, "-m", "tempa.cli.main", "start"],
            cwd=str(settings.project_root),
            start_new_session=True,
        )
        return await daemon_shutdown()

    @app.post("/api/daemon/shutdown")
    async def daemon_shutdown():
        global _shutdown_requested
        _shutdown_requested = True
        asyncio.get_event_loop().call_later(0.5, lambda: __import__("os")._exit(0))
        return {"status": "shutting_down"}

    @app.get("/api/daemon/status")
    async def daemon_status():
        return {"running": True, "shutdown_requested": _shutdown_requested}

    @app.post("/webhooks/whatsapp")
    async def whatsapp_webhook(request: Request):
        from tempa.debug_agent_log import agent_log

        body = await request.body()
        # #region agent log
        agent_log(
            location="app.py:whatsapp_webhook:accepted",
            message="webhook HTTP accepted",
            data={"body_len": len(body)},
            hypothesis_id="H2",
        )
        # #endregion

        async def _process() -> None:
            import json

            try:
                payload = json.loads(body)
            except Exception:
                return
            await handle_webhook(payload)

        asyncio.create_task(_process())
        return {"status": "accepted"}

    @app.websocket("/api/agents/activity")
    async def agents_activity(websocket: WebSocket):
        await websocket.accept()
        queue = await event_bus.subscribe()
        try:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        except WebSocketDisconnect:
            await event_bus.unsubscribe(queue)

    dashboard_dist = settings.project_root / "dashboard" / "dist"
    if dashboard_dist.exists():
        index = dashboard_dist / "index.html"
        assets_dir = dashboard_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="dashboard-assets")

        @app.get("/")
        async def serve_dashboard():
            return FileResponse(index)

        @app.get("/{full_path:path}")
        async def serve_dashboard_spa(full_path: str):
            static_file = dashboard_dist / full_path
            if static_file.is_file():
                return FileResponse(static_file)
            return FileResponse(index)

    return app
