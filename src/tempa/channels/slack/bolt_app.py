from __future__ import annotations

import asyncio
import logging
from typing import Any

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.authorization import AuthorizeResult
from slack_bolt.middleware.assistant.async_assistant import AsyncAssistant
from slack_sdk.web.async_client import AsyncWebClient

from tempa.channels.slack.context import is_dm_event, should_handle_channel_thread
from tempa.channels.slack.conversation import conversation_thread_key, record_conversation_turn
from tempa.channels.slack.messages import GREETING_NEW
from tempa.channels.slack.reply import handle_inbound_slack
from tempa.channels.slack.session import set_handler, slack_configured
from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_slack_app: AsyncApp | None = None
_socket_handler: AsyncSocketModeHandler | None = None
_background_tasks: set[asyncio.Task[None]] = set()
_slack_auth_cache: dict[str, Any] | None = None
_watchdog_task: asyncio.Task[None] | None = None

_SLACK_CLIENT_TIMEOUT_SEC = 30
_WATCHDOG_INTERVAL_SEC = 20.0


async def _touch_socket_envelope(client: Any, req: Any) -> None:
    """Runs ahead of Bolt handle — marks the WebSocket as receiving traffic."""
    from tempa.channels.slack.session import touch_envelope

    touch_envelope()


async def _socket_watchdog_loop() -> None:
    """Reconnect when Slack SDK reports the Socket Mode session is dead.

    Rapid docker restarts leave half-closed WSS sessions; Slack still load-balances
    envelopes onto them for a while, so Tempa looks 'connected' but never replies.
    """
    while True:
        await asyncio.sleep(_WATCHDOG_INTERVAL_SEC)
        handler = _socket_handler
        if handler is None or handler.client is None:
            continue
        try:
            connected = bool(await handler.client.is_connected())
        except Exception:
            connected = False
        if connected:
            continue
        logger.warning("Slack Socket Mode watchdog: session dead — reconnecting")
        try:
            await reconnect_slack_socket_mode()
        except Exception:
            logger.exception("Slack Socket Mode watchdog reconnect failed")


def _ensure_socket_watchdog() -> None:
    global _watchdog_task
    task = _watchdog_task
    if task is not None and not task.done():
        return
    _watchdog_task = asyncio.create_task(_socket_watchdog_loop())


async def stop_socket_watchdog() -> None:
    global _watchdog_task
    task = _watchdog_task
    _watchdog_task = None
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Slack Socket Mode watchdog stop failed")


async def _warm_slack_auth_cache(client: AsyncWebClient) -> None:
    """Resolve team/bot ids once at startup; avoid per-event auth.test calls."""
    global _slack_auth_cache
    settings = get_settings()
    cache: dict[str, Any] = {
        "bot_token": settings.slack_bot_token.strip(),
        "enterprise_id": None,
        "team_id": None,
        "bot_id": None,
        "bot_user_id": None,
    }
    try:
        resp = await client.auth_test(timeout=_SLACK_CLIENT_TIMEOUT_SEC)
        cache.update(
            {
                "enterprise_id": resp.get("enterprise_id"),
                "team_id": resp.get("team_id"),
                "bot_id": resp.get("bot_id"),
                "bot_user_id": resp.get("user_id") if resp.get("bot_id") else None,
            }
        )
        logger.info("Slack auth.test ok (team=%s)", cache.get("team_id"))
    except Exception as exc:
        logger.warning("Slack auth.test failed; using token-only authorize: %s", exc)
    _slack_auth_cache = cache


async def _slack_authorize(**kwargs: Any) -> AuthorizeResult:
    """Authorize Socket Mode events without calling Slack on every message."""
    global _slack_auth_cache
    if _slack_auth_cache is None:
        _slack_auth_cache = {"bot_token": get_settings().slack_bot_token.strip()}
    return AuthorizeResult(
        enterprise_id=_slack_auth_cache.get("enterprise_id") or kwargs.get("enterprise_id"),
        team_id=_slack_auth_cache.get("team_id") or kwargs.get("team_id"),
        bot_id=_slack_auth_cache.get("bot_id"),
        bot_user_id=_slack_auth_cache.get("bot_user_id"),
        bot_token=_slack_auth_cache["bot_token"],
    )


def get_slack_web_client():
    if _slack_app is not None:
        return _slack_app.client
    return None


def _is_dm_event(event: dict) -> bool:
    channel_id = str(event.get("channel") or "")
    return event.get("channel_type") == "im" or channel_id.startswith("D")


async def _process_inbound(
    event: dict,
    *,
    event_type: str,
    event_id: str,
    say,
) -> None:
    try:
        result = await handle_inbound_slack(
            event,
            event_type=event_type,
            event_id=event_id,
            say=say,
        )
        logger.info("Slack inbound %s: %s", event_type, result)
    except Exception:
        logger.exception("Slack inbound handler failed (%s)", event_type)


def _schedule_inbound(
    event: dict,
    *,
    event_type: str,
    event_id: str,
    say,
) -> None:
    task = asyncio.create_task(
        _process_inbound(event, event_type=event_type, event_id=event_id, say=say)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _build_app() -> AsyncApp:
    settings = get_settings()
    client = AsyncWebClient(token=settings.slack_bot_token, timeout=_SLACK_CLIENT_TIMEOUT_SEC)
    app = AsyncApp(
        client=client,
        authorize=_slack_authorize,
        # Socket Mode receives events over WebSocket — no HTTP signing/ssl_check.
        request_verification_enabled=False,
        ssl_check_enabled=False,
    )
    assistant = AsyncAssistant()

    @assistant.thread_started
    async def on_assistant_thread_started(say, set_suggested_prompts, event):
        await set_suggested_prompts(
            prompts=[
                {"title": "Hello", "message": "hi"},
                {"title": "Help", "message": "What can you do?"},
                {"title": "Question", "message": "I have a question"},
            ]
        )
        await say(GREETING_NEW)
        channel_id = str(event.get("channel") or "")
        if channel_id:
            thread_ts = str(event.get("thread_ts") or event.get("ts") or "")
            conv_key = conversation_thread_key(
                channel_id=channel_id,
                thread_ts=thread_ts,
                is_dm=True,
            )
            record_conversation_turn(
                role="assistant",
                text=GREETING_NEW,
                channel_id=channel_id,
                thread_ts=thread_ts,
                conversation_key=conv_key,
            )

    @assistant.user_message
    async def on_assistant_user_message(event, say, body, set_status):
        await set_status("is thinking...")
        from tempa.channels.slack.session import mark_inbound_seen

        event_id = str(body.get("event_id") or "")
        channel_id = str(event.get("channel") or "")
        message_ts = str(event.get("ts") or "")
        # Prefer message-event DM path when both fire; skip duplicate assistant delivery.
        if not mark_inbound_seen(event_id=event_id, channel_id=channel_id, message_ts=message_ts):
            logger.info("Slack assistant duplicate skipped %s", message_ts)
            return
        logger.info(
            "Slack assistant message from %s: %s",
            event.get("user"),
            (event.get("text") or "")[:80],
        )
        _schedule_inbound(
            event,
            event_type="message",
            event_id=event_id,
            say=say,
        )

    app.assistant(assistant)

    @app.event("app_mention")
    async def on_app_mention(event, say, body, ack):
        await ack()
        logger.info("Slack app_mention from %s", event.get("user"))
        _schedule_inbound(
            event,
            event_type="app_mention",
            event_id=str(body.get("event_id") or ""),
            say=say,
        )

    @app.event("message")
    async def on_message(event, say, body, ack):
        if event.get("bot_id") or event.get("subtype"):
            await ack()
            return
        text = str(event.get("text") or "")
        # app_mention owns @Tempa messages — skip here to avoid double replies in threads.
        bot_uid = (_slack_auth_cache or {}).get("bot_user_id")
        if bot_uid and f"<@{bot_uid}>" in text:
            await ack()
            return
        if not _is_dm_event(event):
            if should_handle_channel_thread(event, text):
                await ack()
                logger.info(
                    "Slack channel thread follow-up from %s in %s",
                    event.get("user"),
                    event.get("channel"),
                )
                _schedule_inbound(
                    event,
                    event_type="message",
                    event_id=str(body.get("event_id") or ""),
                    say=say,
                )
            else:
                await ack()
            return
        # DMs: handle here as the primary path. AsyncAssistant may also fire — dedupe by event/ts.
        await ack()
        from tempa.channels.slack.session import mark_inbound_seen

        event_id = str(body.get("event_id") or "")
        channel_id = str(event.get("channel") or "")
        message_ts = str(event.get("ts") or "")
        if not mark_inbound_seen(event_id=event_id, channel_id=channel_id, message_ts=message_ts):
            logger.info("Slack DM duplicate skipped %s", message_ts)
            return
        logger.info(
            "Slack DM from %s: %s",
            event.get("user"),
            text[:80],
        )
        _schedule_inbound(
            event,
            event_type="message",
            event_id=event_id,
            say=say,
        )

    return app


async def start_slack_socket_mode() -> bool:
    """Connect Slack Socket Mode if tokens are configured."""
    global _slack_app, _socket_handler
    if not slack_configured():
        logger.warning("Slack not configured — skipping Socket Mode")
        return False
    # Always reconnect cleanly (stale WS after container recreate breaks replies).
    if _socket_handler is not None:
        await stop_slack_socket_mode()

    settings = get_settings()
    _slack_app = _build_app()
    await _warm_slack_auth_cache(_slack_app.client)
    _socket_handler = AsyncSocketModeHandler(_slack_app, settings.slack_app_token)
    # Envelope listener first so we can tell "WS alive" from "handler replied".
    _socket_handler.client.socket_mode_request_listeners.insert(0, _touch_socket_envelope)
    set_handler(_socket_handler)
    try:
        await _socket_handler.connect_async()
        # Confirm the underlying client thinks it is live.
        connected = False
        try:
            connected = bool(await _socket_handler.client.is_connected())
        except Exception:
            connected = False
        if connected:
            logger.warning("Slack Socket Mode connected (team=%s)", (_slack_auth_cache or {}).get("team_id"))
            from tempa.channels.slack.session import set_error

            set_error(None)
            _ensure_socket_watchdog()
            return True
        logger.error("Slack Socket Mode connect_async returned but client is not connected")
        from tempa.channels.slack.session import set_error

        set_error("Socket Mode connected flag false after connect")
        await stop_slack_socket_mode()
        return False
    except Exception:
        logger.exception("Slack Socket Mode connection failed")
        from tempa.channels.slack.session import set_error

        set_error("Socket Mode connection failed")
        await stop_slack_socket_mode()
        return False


async def reconnect_slack_socket_mode() -> bool:
    """Ops helper — drop and re-open Socket Mode."""
    await stop_slack_socket_mode()
    return await start_slack_socket_mode()


async def stop_slack_socket_mode() -> None:
    global _slack_app, _socket_handler, _slack_auth_cache
    handler = _socket_handler
    _socket_handler = None
    _slack_app = None
    _slack_auth_cache = None
    set_handler(None)
    if handler is not None:
        try:
            # Disconnect first so Slack drops this connection before process exit;
            # otherwise the next container's session shares event delivery with a ghost.
            if hasattr(handler, "disconnect_async"):
                await handler.disconnect_async()
        except Exception:
            logger.exception("Slack Socket Mode disconnect failed")
        try:
            await handler.close_async()
        except Exception:
            logger.exception("Slack Socket Mode shutdown failed")
