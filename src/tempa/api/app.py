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

from tempa.api.dashboard import build_dashboard_payload, build_dashboard_summary
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
from tempa.meet.archive import delete_meeting, erase_all_user_data, export_user_data, get_meeting, init_db, list_meetings, read_live_meeting_state, apply_meet_retention_policy, repair_archives_missing_minutes, sync_meeting_archives_from_disk
from tempa.meet.consent import grant_recording_consent, has_recording_consent, revoke_recording_consent
from tempa.meet.service import get_active_meeting_ids, get_live_meeting_views, get_meeting_jobs, schedule_meeting_join_async
from tempa.meet.scheduler import meet_readiness
from tempa.meet.session_registry import list_active_sessions
from tempa.rag.ingest import ingest_text, search_memory
from tempa.rag.store import get_store
from tempa.router.groq_router import get_router
from tempa.settings import get_settings


class GroqConnectionRequest(BaseModel):
    api_key: str


class JiraConnectionRequest(BaseModel):
    base_url: str
    email: str
    api_token: str = ""
    default_project: str = ""
    enabled: bool = True


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
    kind: str = "preference"


class DurableRequest(BaseModel):
    text: str
    kind: str = "fact"
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
    duration_seconds: int = Field(default=3600, ge=60, le=28800)
    av_test_youtube_url: str | None = None


class MeetingChatRequest(BaseModel):
    text: str


class WhatsAppAllowedNumbersRequest(BaseModel):
    additional_numbers: list[str] = Field(default_factory=list)


_poller_state = load_poller_state()
reminder_state = load_reminder_state()
_scheduler_task: asyncio.Task | None = None
_reminder_task: asyncio.Task | None = None
_gmail_sync_task: asyncio.Task | None = None
_calendar_sync_task: asyncio.Task | None = None
_slack_sync_task: asyncio.Task | None = None
_presence_sync_task: asyncio.Task | None = None
_jira_user_sync_task: asyncio.Task | None = None
_consolidation_task: asyncio.Task | None = None
_retention_task: asyncio.Task | None = None
_shutdown_requested = False


async def _gmail_sync_loop() -> None:
    import logging

    from tempa.channels.gmail.sync import sync_once
    from tempa.core.sync_status import record_sync

    logger = logging.getLogger(__name__)
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

    backoff = interval
    syncing = False

    async def _run_sync(*, full: bool) -> None:
        nonlocal syncing, backoff
        if syncing:
            return
        syncing = True
        try:
            result = await sync_once(full=full)
            status = str(result.get("status", "ok"))
            if status in {"ok", "skipped"}:
                record_sync("gmail", status=status, details=result)
                backoff = interval
            else:
                err = str(result.get("reason") or result.get("error") or status)
                record_sync("gmail", status="error", error=err, details=result)
                backoff = min(backoff * 2, interval * 8)
        except Exception as exc:
            logger.exception("Gmail sync loop failed")
            record_sync("gmail", status="error", error=str(exc))
            backoff = min(backoff * 2, interval * 8)
        finally:
            syncing = False

    if sync_on_startup:
        asyncio.create_task(_run_sync(full=False))

    while True:
        await asyncio.sleep(backoff)
        await _run_sync(full=False)


async def _calendar_sync_loop() -> None:
    import logging

    from tempa.channels.calendar.sync import sync_calendar_snapshot
    from tempa.core.sync_status import record_sync

    logger = logging.getLogger(__name__)
    settings = get_settings()
    try:
        import yaml

        with (settings.config_dir / "permissions.yaml").open(encoding="utf-8") as f:
            cfg = (yaml.safe_load(f) or {}).get("calendar") or {}
        interval = int(cfg.get("poll_interval_seconds", 300))
        sync_on_startup = bool(cfg.get("sync_on_startup", True))
    except Exception:
        interval = 300
        sync_on_startup = True

    backoff = interval
    syncing = False

    async def _run_sync() -> None:
        nonlocal syncing, backoff
        if syncing:
            return
        syncing = True
        try:
            result = await asyncio.to_thread(sync_calendar_snapshot)
            status = str(result.get("status", "ok"))
            if status in {"ok", "skipped"}:
                record_sync("calendar", status=status, details=result)
                backoff = interval
            else:
                err = str(result.get("reason") or status)
                record_sync("calendar", status="error", error=err, details=result)
                backoff = min(backoff * 2, interval * 8)
        except Exception as exc:
            logger.exception("Calendar sync loop failed")
            record_sync("calendar", status="error", error=str(exc))
            backoff = min(backoff * 2, interval * 8)
        finally:
            syncing = False

    if sync_on_startup:
        asyncio.create_task(_run_sync())

    while True:
        await asyncio.sleep(backoff)
        await _run_sync()


async def _slack_sync_loop() -> None:
    import logging

    from tempa.channels.slack.sync import sync_once as sync_slack_once
    from tempa.channels.slack.session import slack_configured
    from tempa.core.sync_status import record_sync

    logger = logging.getLogger(__name__)
    if not slack_configured():
        return

    settings = get_settings()
    try:
        import yaml

        with (settings.config_dir / "permissions.yaml").open(encoding="utf-8") as f:
            cfg = (yaml.safe_load(f) or {}).get("slack") or {}
        interval = int(cfg.get("poll_interval_seconds", 300))
        sync_on_startup = bool(cfg.get("sync_on_startup", True))
    except Exception:
        interval = 300
        sync_on_startup = True

    backoff = interval
    syncing = False

    async def _run_sync(*, full: bool) -> None:
        nonlocal syncing, backoff
        if syncing:
            return
        syncing = True
        try:
            result = await sync_slack_once(full=full)
            status = str(result.get("status", "ok"))
            if status in {"ok", "skipped"}:
                record_sync("slack", status=status, details=result)
                backoff = interval
            else:
                err = str(result.get("reason") or result.get("error") or status)
                record_sync("slack", status="error", error=err, details=result)
                backoff = min(backoff * 2, interval * 8)
        except Exception as exc:
            logger.exception("Slack sync loop failed")
            record_sync("slack", status="error", error=str(exc))
            backoff = min(backoff * 2, interval * 8)
        finally:
            syncing = False

    if sync_on_startup:
        asyncio.create_task(_run_sync(full=True))

    while True:
        await asyncio.sleep(backoff)
        await _run_sync(full=False)


async def _presence_sync_loop() -> None:
    import logging

    from tempa.channels.slack.presence_sync import sync_presence_async
    from tempa.channels.slack.session import slack_configured
    from tempa.core.sync_status import record_sync

    logger = logging.getLogger(__name__)
    if not slack_configured():
        return
    if not get_settings().slack_presence_channel_id.strip():
        return

    interval = 60
    backoff = interval
    syncing = False

    async def _run_sync() -> None:
        nonlocal syncing, backoff
        if syncing:
            return
        syncing = True
        try:
            result = await sync_presence_async()
            status = str(result.get("status", "ok"))
            if status in {"ok", "skipped"}:
                record_sync("presence", status=status, details=result)
                backoff = interval
            else:
                err = str(result.get("reason") or result.get("error") or status)
                record_sync("presence", status="error", error=err, details=result)
                backoff = min(backoff * 2, interval * 8)
        except Exception as exc:
            logger.exception("Presence sync loop failed")
            record_sync("presence", status="error", error=str(exc))
            backoff = min(backoff * 2, interval * 8)
        finally:
            syncing = False

    asyncio.create_task(_run_sync())
    while True:
        await asyncio.sleep(backoff)
        await _run_sync()


async def _jira_user_sync_loop() -> None:
    import logging

    from tempa.channels.jira.client import jira_configured
    from tempa.channels.jira.sync import sync_jira_users
    from tempa.core.sync_status import record_sync

    logger = logging.getLogger(__name__)
    if not jira_configured():
        return

    interval = 6 * 3600
    backoff = interval
    syncing = False

    async def _run_sync() -> None:
        nonlocal syncing, backoff
        if syncing:
            return
        syncing = True
        try:
            result = await sync_jira_users()
            status = str(result.get("status", "ok"))
            if status in {"ok", "skipped"}:
                record_sync("jira_users", status=status, details=result)
                backoff = interval
            else:
                err = str(result.get("reason") or status)
                record_sync("jira_users", status="error", error=err, details=result)
                backoff = min(backoff * 2, interval * 4)
        except Exception as exc:
            logger.exception("Jira user sync loop failed")
            record_sync("jira_users", status="error", error=str(exc))
            backoff = min(backoff * 2, interval * 4)
        finally:
            syncing = False

    asyncio.create_task(_run_sync())

    while True:
        await asyncio.sleep(backoff)
        await _run_sync()


async def _calendar_loop() -> None:
    import logging

    from tempa.meet.scheduler import schedule_join_for_calendar_event

    logger = logging.getLogger(__name__)

    async def on_trigger(ev):
        return await schedule_join_for_calendar_event(ev)

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
    global _scheduler_task, _reminder_task, _gmail_sync_task, _calendar_sync_task, _slack_sync_task, _presence_sync_task, _jira_user_sync_task, _consolidation_task, _retention_task
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

    async def _sync_meeting_archives_background() -> None:
        import logging

        log = logging.getLogger(__name__)
        try:
            synced = await sync_meeting_archives_from_disk()
            repaired = await repair_archives_missing_minutes(min_segments=3)
            if synced or repaired:
                log.info("Meeting archives: synced %s from disk, repaired %s minutes", synced, repaired)
        except Exception as exc:
            log.warning("Meeting archive sync failed: %s", exc)

    asyncio.create_task(_sync_meeting_archives_background(), name="meeting-archive-sync")
    await init_contacts_db()
    sweep_stale_tasks()

    async def _warm_embedder_background() -> None:
        import logging

        log = logging.getLogger(__name__)

        def _warm() -> None:
            from tempa.rag.embeddings import get_embedder

            get_embedder().embed("tempa warmup")

        try:
            await asyncio.to_thread(_warm)
            log.info("Embedder warmup complete")
        except Exception as exc:
            log.warning("Embedder warmup failed (RAG may be unavailable): %s", exc)

    asyncio.create_task(_warm_embedder_background(), name="embedder-warmup")
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

    from tempa.channels.slack.bolt_app import start_slack_socket_mode
    from tempa.channels.slack.session import slack_configured

    if slack_configured():
        try:
            await start_slack_socket_mode()
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("Slack startup failed: %s", exc)

    # Start Cursor worker in main lifespan (not deferred) so pinned Slack asks never sit unclaimed.
    try:
        from tempa.channels.slack.cursor_worker import start_cursor_worker
        import logging as _log

        await start_cursor_worker()
        _log.getLogger(__name__).info("Cursor Slack worker started")
    except Exception:
        import logging as _log

        _log.getLogger(__name__).exception("Cursor Slack worker failed to start")

    async def _deferred_background() -> None:
        global _scheduler_task, _reminder_task, _gmail_sync_task, _calendar_sync_task, _slack_sync_task, _presence_sync_task, _jira_user_sync_task, _consolidation_task, _retention_task
        import logging as _log

        _log.getLogger(__name__).info("Deferred background starting")
        await asyncio.sleep(2)
        # Cursor worker first — must not wait behind QA install sync / other startup.
        try:
            from tempa.channels.slack.cursor_worker import start_cursor_worker

            await start_cursor_worker()
            _log.getLogger(__name__).info("Cursor Slack worker started")
        except Exception:
            _log.getLogger(__name__).exception("Cursor Slack worker failed to start")
        _scheduler_task = asyncio.create_task(_calendar_loop())
        _reminder_task = asyncio.create_task(_reminder_loop())
        _gmail_sync_task = asyncio.create_task(_gmail_sync_loop())
        _calendar_sync_task = asyncio.create_task(_calendar_sync_loop())
        _slack_sync_task = asyncio.create_task(_slack_sync_loop())
        _presence_sync_task = asyncio.create_task(_presence_sync_loop())
        _jira_user_sync_task = asyncio.create_task(_jira_user_sync_loop())
        _consolidation_task = asyncio.create_task(_consolidation_loop())
        _retention_task = asyncio.create_task(_retention_loop())
        try:
            from tempa.channels.contacts.sync import sync_contacts

            asyncio.create_task(sync_contacts())
        except Exception:
            pass
        try:
            from tempa.channels.jira.client import jira_configured
            from tempa.channels.jira.sync import sync_jira_users

            if jira_configured():
                asyncio.create_task(sync_jira_users())
        except Exception:
            pass
        try:
            from tempa.pc.transfer.server import ensure_transfer_server

            asyncio.create_task(ensure_transfer_server())
        except Exception:
            pass
        try:
            from tempa.qa.config import qa_enabled
            from tempa.qa.worker import start_qa_worker

            if qa_enabled():
                await start_qa_worker()
                _log.getLogger(__name__).info("QA worker started")
            else:
                _log.getLogger(__name__).info("QA worker skipped (disabled)")
        except Exception:
            _log.getLogger(__name__).exception("QA worker failed to start")
        try:
            from tempa.varys.tick import start_varys_tick_loop

            await start_varys_tick_loop()
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
    if _calendar_sync_task:
        _calendar_sync_task.cancel()
    if _slack_sync_task:
        _slack_sync_task.cancel()
    if _presence_sync_task:
        _presence_sync_task.cancel()
    if _jira_user_sync_task:
        _jira_user_sync_task.cancel()
    try:
        from tempa.pc.transfer.server import stop_transfer_server

        await stop_transfer_server()
    except Exception:
        pass
    await stop_inbound_worker()
    try:
        from tempa.qa.worker import stop_qa_worker

        await stop_qa_worker()
    except Exception:
        pass
    try:
        from tempa.channels.slack.cursor_worker import stop_cursor_worker

        await stop_cursor_worker()
    except Exception:
        pass
    try:
        from tempa.varys.tick import stop_varys_tick_loop

        await stop_varys_tick_loop()
    except Exception:
        pass
    try:
        from tempa.channels.slack.bolt_app import stop_slack_socket_mode

        await stop_slack_socket_mode()
    except Exception:
        pass
    encrypt_sensitive_sessions()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Tempa Daemon", version="0.1.0", lifespan=lifespan)
    from tempa.api.features import router as features_router
    from tempa.api.presence import router as presence_router
    from tempa.api.qa import router as qa_router

    app.include_router(features_router, prefix="/api")
    app.include_router(qa_router, prefix="/api")
    app.include_router(presence_router, prefix="/api")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.tempa_cors_origin] if settings.tempa_cors_origin != "*" else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/dashboard")
    async def dashboard_status(refresh: bool = False):
        return await build_dashboard_payload(refresh=refresh)

    @app.get("/api/dashboard/summary")
    async def dashboard_summary(refresh: bool = False):
        return await build_dashboard_summary(refresh=refresh)

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
            from tempa.meet.worker_heartbeat import read_worker_heartbeat, worker_is_alive

            delegate = os.environ.get("TEMPA_MEET_DELEGATE_TO_WORKER", "").lower() in ("1", "true", "yes")
            jobs = get_meeting_jobs()
            queued = sum(1 for j in jobs.values() if j.get("status") == "queued")
            running = sum(1 for j in jobs.values() if j.get("status") in ("running", "finalizing"))
            mode = "delegated" if delegate else "in_process"
            alive = worker_is_alive() if delegate else True
            status = "ok" if alive or queued == 0 else "degraded"
            if delegate and queued > 0 and not alive:
                status = "degraded"
            return {
                "status": status,
                "mode": mode,
                "queued": queued,
                "running": running,
                "worker_alive": alive,
                "heartbeat": read_worker_heartbeat(),
            }

        def _cursor_check() -> dict[str, Any]:
            from pathlib import Path

            from tempa.channels.slack.cursor_threads import load_cursor_threads
            from tempa.channels.slack.cursor_worktree import git_available, worktree_root
            from tempa.channels.slack.cursor_pr import gh_available
            from tempa.qa.cursor import cursor_configured

            mounts = []
            for row in load_cursor_threads():
                cwd = str(row.get("local_cwd") or "")
                ok = bool(cwd) and Path(cwd).is_dir()
                writable = ok and os.access(cwd, os.W_OK)
                mounts.append({"cwd": cwd, "exists": ok, "writable": writable, "label": row.get("label")})
            try:
                wr = worktree_root()
                wr_ok = wr.is_dir() and os.access(wr, os.W_OK)
            except Exception as exc:
                wr_ok = False
                wr = str(exc)[:120]
            sdk_ok = False
            try:
                import cursor_sdk  # noqa: F401

                sdk_ok = True
            except Exception:
                sdk_ok = False
            status = "ok"
            if not cursor_configured() or not sdk_ok:
                status = "degraded"
            if any(m.get("cwd") and not m.get("writable") for m in mounts):
                status = "degraded"
            if not git_available() or not gh_available():
                status = "degraded"
            if not wr_ok:
                status = "degraded"
            try:
                from tempa.channels.slack import cursor_worker as cw

                worker_alive = bool(cw._worker_task and not cw._worker_task.done())
            except Exception:
                worker_alive = False
            return {
                "status": status,
                "cursor_api_key": cursor_configured(),
                "cursor_sdk": sdk_ok,
                "git": git_available(),
                "gh": gh_available(),
                "worktree_root": str(wr),
                "worktree_writable": wr_ok,
                "worker_alive": worker_alive,
                "mounts": mounts,
            }

        chroma, groq, meet_worker, cursor = await asyncio.gather(
            asyncio.to_thread(_chromadb_check),
            asyncio.to_thread(_groq_check),
            asyncio.to_thread(_meet_worker_check),
            asyncio.to_thread(_cursor_check),
        )
        components["chromadb"] = chroma
        components["groq"] = groq
        components["meet_worker"] = meet_worker
        components["cursor"] = cursor

        overall = "ok"
        if chroma.get("status") == "error" or groq.get("status") == "degraded":
            overall = "degraded"
        if cursor.get("status") == "degraded":
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

    @app.get("/api/skills")
    async def list_skills():
        from tempa.skills import load_all_skills

        return {
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "triggers": s.triggers,
                    "workers": s.workers,
                    "tools": s.tools,
                    "channels": s.channels,
                    "enabled": True,
                }
                for s in load_all_skills()
            ]
        }

    @app.get("/api/orchestrator")
    async def orchestrator_manifest():
        from tempa.orchestrator.registry import orchestrator_manifest

        return orchestrator_manifest()

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

    @app.get("/api/connections/slack")
    async def slack_status():
        from tempa.channels.slack.session import connection_status

        return await connection_status()

    @app.get("/api/connections/jira")
    async def jira_status():
        from tempa.channels.jira.status import jira_connection_status

        return await asyncio.to_thread(jira_connection_status)

    @app.post("/api/connections/jira")
    async def connect_jira(body: JiraConnectionRequest):
        from tempa.channels.jira.client import test_connection
        from tempa.channels.jira.session import load_jira_api_token, save_jira_session_config

        token = body.api_token.strip() or load_jira_api_token()
        if not body.base_url.strip() or not body.email.strip() or not token:
            return {
                "status": "error",
                "detail": "Base URL, email, and API token are required",
                "connected": False,
            }
        save_jira_session_config(
            base_url=body.base_url,
            email=body.email,
            default_project=body.default_project,
            api_token=token if body.api_token.strip() else None,
        )
        settings.jira_base_url = body.base_url.strip().rstrip("/")
        settings.jira_email = body.email.strip()
        settings.jira_default_project = body.default_project.strip()
        settings.jira_enabled = body.enabled
        if body.api_token.strip():
            settings.jira_api_token = body.api_token.strip()
        try:
            result = await asyncio.to_thread(test_connection)
            try:
                from tempa.channels.jira.sync import sync_jira_users

                asyncio.create_task(sync_jira_users())
            except Exception:
                pass
            return {
                "status": "connected",
                "connected": True,
                "display_name": result.get("display_name"),
                "detail": result.get("display_name") or "Connected",
            }
        except Exception as exc:
            return {"status": "error", "connected": False, "detail": str(exc)[:200]}

    @app.delete("/api/connections/jira")
    async def disconnect_jira():
        from tempa.channels.jira.session import clear_jira_session

        clear_jira_session()
        settings.jira_base_url = ""
        settings.jira_email = ""
        settings.jira_api_token = ""
        settings.jira_default_project = ""
        settings.jira_enabled = False
        return {"status": "disconnected", "connected": False}

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
            stream_steps: list[dict[str, Any]] = []
            stream_activity: list[dict[str, Any]] = []

            def _merge_stream_step(step: dict[str, Any]) -> None:
                if step.get("status") == "start":
                    stream_steps.append(step)
                else:
                    for i, existing in enumerate(stream_steps):
                        if (
                            existing.get("subtask_id") == step.get("subtask_id")
                            and existing.get("status") == "start"
                        ):
                            stream_steps[i] = {**existing, **step}
                            break
                    else:
                        stream_steps.append(step)
                if len(stream_steps) > 50:
                    del stream_steps[:-50]

            session = ensure_session(body.session_id)
            session_id = session["id"]
            append_message(session_id, "user", body.message)
            asyncio.create_task(
                asyncio.to_thread(
                    ingest_text,
                    body.message,
                    tool="dashboard",
                    source=session_id,
                    tags=["inbound"],
                )
            )
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
                                _merge_stream_step(event)
                                await queue.put(("step", event))
                            else:
                                stream_activity.append(
                                    {
                                        "agent": str(event.get("agent", "")),
                                        "action": str(event.get("action", "")),
                                        "detail": str(event.get("detail", "")),
                                        "timestamp": str(event.get("timestamp", "")),
                                    }
                                )
                                if len(stream_activity) > 50:
                                    del stream_activity[:-50]
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
                    planned_steps = result.get("planned_steps") or []
                    if content or paused or pending_actions or artifacts:
                        append_message(
                            session_id,
                            "assistant",
                            content,
                            sources=sources,
                            paused=paused,
                            steps=stream_steps or None,
                            activity=stream_activity or None,
                            pending_actions=pending_actions or None,
                            artifacts=artifacts or None,
                            planned_steps=planned_steps or None,
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
                                "planned_steps": planned_steps,
                                "run_id": run_id,
                            },
                        )
                    )
                except asyncio.CancelledError:
                    await queue.put(
                        (
                            "error",
                            {
                                "error": "Run cancelled",
                                "code": "CANCELLED",
                                "recoverable": False,
                            },
                        )
                    )
                except Exception as exc:
                    from tempa.core.chat_errors import classify_exception

                    await queue.put(("error", classify_exception(exc)))
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
    async def memory_preferences_list(kind: str | None = None):
        from tempa.rag.procedural import list_durable, list_preferences

        if kind:
            return {"preferences": list_durable(kinds=[kind])}
        return {"preferences": list_preferences()}

    @app.post("/api/memory/preferences")
    async def memory_preferences_add(body: PreferenceRequest):
        from tempa.rag.procedural import add_durable, add_preference

        if body.kind and body.kind != "preference":
            return add_durable(body.rule, kind=body.kind, source=body.source, tags=body.tags)
        return add_preference(body.rule, source=body.source, tags=body.tags)

    @app.get("/api/memory/durable")
    async def memory_durable_list(kind: str | None = None):
        from tempa.rag.procedural import list_durable

        kinds = [kind] if kind else None
        return {"items": list_durable(kinds=kinds)}

    @app.post("/api/memory/durable")
    async def memory_durable_add(body: DurableRequest):
        from tempa.rag.procedural import add_durable

        return add_durable(body.text, kind=body.kind, source=body.source, tags=body.tags)

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

    @app.post("/api/meetings/sync-archives")
    async def meetings_sync_archives():
        synced = await sync_meeting_archives_from_disk()
        repaired = await repair_archives_missing_minutes(min_segments=3)
        return {
            "synced": synced,
            "minutes_repaired": repaired,
            "meetings": await list_meetings(),
        }

    @app.get("/api/meetings/youtube-status")
    async def meetings_youtube_status():
        from tempa.meet.youtube_upload import youtube_upload_status

        return await asyncio.to_thread(youtube_upload_status)

    @app.post("/api/meetings/youtube-backfill")
    async def meetings_youtube_backfill():
        from tempa.meet.youtube_upload import backfill_youtube_uploads

        result = await backfill_youtube_uploads()
        return {**result, "meetings": await list_meetings()}

    @app.post("/api/meetings/process-audio")
    async def meetings_process_audio():
        from tempa.meet.transcribe import process_meetings_with_audio

        results = await process_meetings_with_audio(send_notifications=False)
        return {"processed": results, "meetings": await list_meetings()}

    @app.post("/api/meetings/{meeting_id}/transcribe")
    async def meeting_transcribe(meeting_id: str):
        from tempa.meet.transcribe import transcribe_meeting_audio

        try:
            segment_count = await transcribe_meeting_audio(meeting_id, force=True)
            return {
                "status": "ok",
                "meeting_id": meeting_id,
                "transcript_segments": segment_count,
                "meeting": await get_meeting(meeting_id),
            }
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    @app.post("/api/meetings/{meeting_id}/summarize")
    async def meeting_summarize(meeting_id: str):
        from tempa.meet.transcribe import summarize_meeting_from_transcript

        try:
            await summarize_meeting_from_transcript(meeting_id, send_notifications=False)
            return {"status": "ok", "meeting": await get_meeting(meeting_id)}
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    @app.post("/api/meetings/{meeting_id}/process")
    async def meeting_process(meeting_id: str):
        from tempa.meet.transcribe import process_meeting_from_audio

        try:
            result = await process_meeting_from_audio(meeting_id, send_notifications=False)
            return {"status": "ok", **result, "meeting": await get_meeting(meeting_id)}
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

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
                duration_seconds=body.duration_seconds,
                av_test_youtube_url=body.av_test_youtube_url,
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
        sessions = list_active_sessions()
        live = await asyncio.to_thread(get_live_meeting_views)
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
        from tempa.meet.media import list_meeting_media

        media = list_meeting_media(
            meeting_id,
            audio_path_hint=str(meeting.get("audio_path") or ""),
        )
        return {
            "meeting": meeting,
            "transcript_raw": transcript,
            "pending_followups": pending,
            "media": media,
        }

    @app.get("/api/meetings/{meeting_id}/transcript")
    async def meeting_transcript_download(meeting_id: str):
        from tempa.meet.media import resolve_transcript_path

        path = resolve_transcript_path(meeting_id)
        if not path:
            return {"error": "transcript_not_found"}
        return FileResponse(path, media_type="application/x-ndjson", filename=path.name)

    @app.get("/api/meetings/{meeting_id}/video")
    async def meeting_video(meeting_id: str):
        from tempa.meet.media import resolve_playable_video_path

        meeting = await get_meeting(meeting_id)
        if not meeting:
            return {"error": "not_found"}
        path = await asyncio.to_thread(
            resolve_playable_video_path,
            meeting_id,
            audio_path_hint=str(meeting.get("audio_path") or ""),
        )
        if not path:
            return {"error": "video_not_found"}
        media_type = "video/mp4" if path.suffix.lower() == ".mp4" else "video/webm"
        return FileResponse(path, media_type=media_type, filename=path.name)

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

    @app.get("/api/meetings/{meeting_id}/waveform")
    async def meeting_waveform(meeting_id: str, bars: int = 72):
        from tempa.meet.media import compute_audio_waveform

        meeting = await get_meeting(meeting_id)
        if not meeting:
            return {"error": "not_found", "available": False, "duration_seconds": 0.0, "peaks": []}
        return await asyncio.to_thread(
            compute_audio_waveform,
            meeting_id,
            audio_path_hint=str(meeting.get("audio_path") or ""),
            bars=bars,
        )

    @app.get("/api/meetings/{meeting_id}/storyboard")
    async def meeting_storyboard(meeting_id: str):
        from tempa.meet.media import compute_video_storyboard

        meeting = await get_meeting(meeting_id)
        if not meeting:
            return {"error": "not_found", "available": False}
        return await asyncio.to_thread(compute_video_storyboard, meeting_id)

    @app.get("/api/meetings/{meeting_id}/storyboard/sprite")
    async def meeting_storyboard_sprite(meeting_id: str):
        from tempa.meet.media import compute_video_storyboard, resolve_storyboard_sprite_path

        meeting = await get_meeting(meeting_id)
        if not meeting:
            return {"error": "not_found"}
        await asyncio.to_thread(compute_video_storyboard, meeting_id)
        path = resolve_storyboard_sprite_path(meeting_id)
        if not path:
            return {"error": "storyboard_not_found"}
        return FileResponse(path, media_type="image/jpeg", filename=path.name)

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

        import json

        try:
            payload = json.loads(body)
        except Exception:
            return {"status": "ignored", "reason": "invalid_json"}
        result = await handle_webhook(payload)
        return {"status": "accepted", **result}

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
