from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_task: asyncio.Task[None] | None = None
_task_started_at: float = 0.0
_last_error: str | None = None
_last_success_at: float = 0.0
_stuck_restart_count: int = 0
_first_fetch_at: float = 0.0
_connecting_since: float = 0.0

# Serialize Evolution connect/restart — concurrent calls break pairing.
_evolution_lock = asyncio.Lock()
_STUCK_SECONDS = 90
_CONNECTING_STUCK_SECONDS = 120
_TASK_STALE_SECONDS = 150
_FETCH_COOLDOWN_SECONDS = 90
_last_scheduled_at: float = 0.0


def _webhook_url() -> str:
    from tempa.settings import get_settings

    settings = get_settings()
    base = settings.tempa_webhook_base_url.strip() or (
        f"http://127.0.0.1:{settings.tempa_daemon_port}"
    )
    return f"{base.rstrip('/')}/webhooks/whatsapp"


def last_qr_error() -> str | None:
    return _last_error


def qr_task_running() -> bool:
    return _task is not None and not _task.done()


def _set_error(msg: str | None) -> None:
    global _last_error
    _last_error = msg
    if msg:
        logger.warning("WhatsApp QR: %s", msg)


def _cancel_task() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
    _task = None


async def _run_fetch(*, refresh: bool) -> None:
    global _last_success_at
    from tempa.channels.whatsapp.client import WhatsAppBridgeClient
    from tempa.channels.whatsapp.session import get_qr_code
    from tempa.debug_agent_log import agent_log

    client = WhatsAppBridgeClient()
    webhook_url = _webhook_url()
    try:
        state_name, connected = await client.resolved_connection_state()
        # #region agent log
        agent_log(
            location="qr_tasks.py:_run_fetch:entry",
            message="fetch task started",
            data={"refresh": refresh, "state_name": state_name, "connected": connected},
            hypothesis_id="H2",
        )
        # #endregion
        if connected:
            _set_error(None)
            return
        if state_name == "connecting" and get_qr_code():
            # #region agent log
            agent_log(
                location="qr_tasks.py:_run_fetch:skip",
                message="skipped fetch — cached QR while connecting",
                data={},
                hypothesis_id="H5",
            )
            # #endregion
            logger.info("WhatsApp pairing in progress — cached QR available")
            return
        if state_name == "connecting":
            # #region agent log
            agent_log(
                location="qr_tasks.py:_run_fetch:wait",
                message="waiting for QR while connecting — no reconnect",
                data={},
                hypothesis_id="H9",
            )
            # #endregion
            async with _evolution_lock:
                result = await client.poll_connect_qr(attempts=30)
            qr = result.get("qr_code")
            if qr:
                _set_error(None)
                _last_success_at = time.monotonic()
            else:
                _set_error(
                    result.get("detail")
                    or "QR not ready yet — WhatsApp bridge is still generating the code"
                )
            # #region agent log
            agent_log(
                location="qr_tasks.py:_run_fetch:exit",
                message="fetch task finished",
                data={"qr_len": len(qr or ""), "error": _last_error, "result_status": result.get("status")},
                hypothesis_id="H9",
            )
            # #endregion
            return
    except Exception:
        pass

    try:
        await client.ensure_instance(webhook_url=webhook_url)
    except Exception as exc:
        msg = str(exc).strip() or repr(exc)
        _set_error(f"WhatsApp bridge setup failed: {msg}")
        logger.error("WhatsApp bridge setup failed: %s", msg)
        return

    try:
        async with _evolution_lock:
            result = await client.fetch_qr(refresh=refresh)
        qr = result.get("qr_code")
        if qr:
            _set_error(None)
            _last_success_at = time.monotonic()
            logger.info("WhatsApp QR ready (status=%s)", result.get("status"))
        else:
            _set_error(
                result.get("detail")
                or "QR not ready yet — WhatsApp bridge is still generating the code"
            )
        # #region agent log
        agent_log(
            location="qr_tasks.py:_run_fetch:exit",
            message="fetch task finished",
            data={"qr_len": len(qr or ""), "error": _last_error, "result_status": result.get("status")},
            hypothesis_id="H2",
        )
        # #endregion
    except Exception as exc:
        msg = str(exc).strip() or repr(exc)
        _set_error(f"QR fetch failed: {msg}")
        logger.exception("WhatsApp QR fetch failed: %s", msg)


async def _run_restart() -> None:
    """Vendor-aligned recovery: restart websocket or reconnect — never delete instance."""
    global _stuck_restart_count, _last_success_at
    from tempa.channels.whatsapp.client import WhatsAppBridgeClient
    from tempa.channels.whatsapp.session import get_qr_code, update_connection_state

    client = WhatsAppBridgeClient()
    webhook_url = _webhook_url()
    try:
        logger.info("WhatsApp session recovery (vendor restart/connect)")
        async with _evolution_lock:
            result = await client.restart_instance(webhook_url)
        state_name, connected = await client.resolved_connection_state()
        update_connection_state("open" if connected else state_name)
        qr = result.get("qr_code") or get_qr_code()
        if qr or connected:
            _set_error(None)
            _last_success_at = time.monotonic()
            logger.info("WhatsApp session recovery — %s", "connected" if connected else "QR available")
        else:
            _set_error("Session recovery — waiting for QR from WhatsApp bridge")
        _stuck_restart_count += 1
    except Exception as exc:
        _set_error(f"Session recovery failed: {exc}")
        logger.exception("WhatsApp session recovery failed")


def _start_task(coro) -> None:
    global _task, _task_started_at
    from tempa.debug_agent_log import agent_log

    async def _wrap() -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _set_error(f"Background task failed: {exc}")
            logger.exception("WhatsApp background task failed")

    if _task and not _task.done():
        age = time.monotonic() - _task_started_at
        if age < _TASK_STALE_SECONDS:
            # #region agent log
            agent_log(
                location="qr_tasks.py:_start_task:skip",
                message="task already running",
                data={"age_s": round(age, 1)},
                hypothesis_id="H3",
            )
            # #endregion
            return
        _task.cancel()

    _task = asyncio.create_task(_wrap())
    _task_started_at = time.monotonic()
    # #region agent log
    agent_log(
        location="qr_tasks.py:_start_task:start",
        message="background task started",
        data={},
        hypothesis_id="H3",
    )
    # #endregion


async def schedule_fetch_qr(*, refresh: bool = False) -> None:
    """Kick off QR fetch in the background; safe to call repeatedly."""
    global _last_scheduled_at
    now = time.monotonic()
    if refresh:
        _cancel_task()
        _last_scheduled_at = 0.0
    elif qr_task_running():
        return
    elif _last_scheduled_at and now - _last_scheduled_at < _FETCH_COOLDOWN_SECONDS:
        return
    _last_scheduled_at = now

    async def _run() -> None:
        await _run_fetch(refresh=refresh)

    _start_task(_run())


async def schedule_restart(webhook_url: str | None = None) -> None:
    """Recover session in the background (vendor restart, not delete)."""
    del webhook_url

    async def _run() -> None:
        await _run_restart()

    _start_task(_run())


async def auto_manage_connection(*, await_fetch: bool = False) -> dict[str, Any]:
    """
    Vendor-aligned flow: ensure instance + webhook, GET /instance/connect for QR.
    """
    global _first_fetch_at, _connecting_since
    from tempa.channels.whatsapp.client import WhatsAppBridgeClient
    from tempa.channels.whatsapp.session import get_qr_code

    client = WhatsAppBridgeClient()
    try:
        state_name, connected = await client.resolved_connection_state()
    except Exception as exc:
        _set_error(f"WhatsApp bridge unreachable: {exc}")
        return {
            "action": "error",
            "status": "error",
            "qr_code": None,
            "detail": _last_error,
        }

    if connected:
        _set_error(None)
        _first_fetch_at = 0.0
        _connecting_since = 0.0
        _cancel_task()
        return {"action": "connected", "status": state_name, "qr_code": None}

    cached = get_qr_code()
    now = time.monotonic()

    if state_name == "connecting":
        synced = await client.read_cached_qr()
        if synced:
            _connecting_since = 0.0
            _set_error(None)
            return {
                "action": "connecting",
                "status": state_name,
                "qr_code": synced,
                "detail": "Scan the QR with WhatsApp → Settings → Linked devices",
            }
        if _connecting_since == 0.0:
            _connecting_since = now
        if not qr_task_running():
            await schedule_fetch_qr(refresh=False)
        return {
            "action": "connecting",
            "status": state_name,
            "qr_code": None,
            "detail": _last_error or "Waiting for QR from WhatsApp bridge",
        }

    _connecting_since = 0.0

    if _first_fetch_at == 0.0:
        _first_fetch_at = now
    if cached:
        _first_fetch_at = 0.0
        return {
            "action": "cached",
            "status": state_name,
            "qr_code": cached,
            "detail": None,
        }

    stuck = (
        not cached
        and state_name in {"close", "disconnected", "refused"}
        and now - _first_fetch_at > _STUCK_SECONDS
        and not qr_task_running()
    )
    if stuck and _stuck_restart_count < 1:
        _first_fetch_at = now
        await schedule_fetch_qr(refresh=True)
        return {
            "action": "fetch",
            "status": state_name,
            "qr_code": cached,
            "detail": _last_error or "Fetching new QR",
        }
    if stuck and _stuck_restart_count < 3:
        _first_fetch_at = now
        if await_fetch:
            await _run_restart()
            cached = get_qr_code()
            return {
                "action": "restart",
                "status": state_name,
                "qr_code": cached,
                "detail": _last_error,
            }
        await schedule_restart()
        return {
            "action": "restart",
            "status": state_name,
            "qr_code": cached,
            "detail": _last_error or "Reconnecting — fetching new QR",
        }

    if await_fetch:
        if _task and not _task.done():
            _task.cancel()
        await _run_fetch(refresh=True)
        cached = get_qr_code()
        return {
            "action": "fetch",
            "status": state_name,
            "qr_code": cached,
            "detail": _last_error,
        }

    if not qr_task_running() and (_first_fetch_at == 0.0 or now - _first_fetch_at > _FETCH_COOLDOWN_SECONDS):
        _first_fetch_at = now
        await schedule_fetch_qr(refresh=False)
    result = {
        "action": "fetch",
        "status": state_name,
        "qr_code": cached,
        "detail": _last_error if qr_task_running() and _last_error else _last_error,
    }
    # #region agent log
    from tempa.debug_agent_log import agent_log

    agent_log(
        location="qr_tasks.py:auto_manage:exit",
        message="auto_manage result",
        data={"action": result["action"], "state": state_name, "cached_qr": bool(cached)},
        hypothesis_id="H3",
    )
    # #endregion
    return result
