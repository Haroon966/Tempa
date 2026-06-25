from __future__ import annotations

import asyncio
import logging
from typing import Any

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.authorization import AuthorizeResult
from slack_bolt.middleware.assistant.async_assistant import AsyncAssistant
from slack_sdk.web.async_client import AsyncWebClient

from tempa.channels.slack.reply import handle_inbound_slack
from tempa.channels.slack.session import set_handler, slack_configured
from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_slack_app: AsyncApp | None = None
_socket_handler: AsyncSocketModeHandler | None = None
_background_tasks: set[asyncio.Task[None]] = set()
_slack_auth_cache: dict[str, Any] | None = None

_SLACK_CLIENT_TIMEOUT_SEC = 30


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
    async def on_assistant_thread_started(say, set_suggested_prompts):
        await set_suggested_prompts(
            prompts=[
                {"title": "Hello", "message": "hi"},
                {"title": "Help", "message": "What can you do?"},
                {"title": "Question", "message": "I have a question"},
            ]
        )
        await say("Hi — I'm Tempa. How can I help?")

    @assistant.user_message
    async def on_assistant_user_message(event, say, body, set_status):
        await set_status("is thinking...")
        logger.info(
            "Slack assistant message from %s: %s",
            event.get("user"),
            (event.get("text") or "")[:80],
        )
        _schedule_inbound(
            event,
            event_type="message",
            event_id=str(body.get("event_id") or ""),
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
        if not _is_dm_event(event):
            await ack()
            return
        await ack()
        logger.info("Slack DM from %s: %s", event.get("user"), (event.get("text") or "")[:80])
        _schedule_inbound(
            event,
            event_type="message",
            event_id=str(body.get("event_id") or ""),
            say=say,
        )

    return app


async def start_slack_socket_mode() -> bool:
    """Connect Slack Socket Mode if tokens are configured."""
    global _slack_app, _socket_handler
    if not slack_configured():
        return False
    if _socket_handler is not None:
        return True

    settings = get_settings()
    _slack_app = _build_app()
    await _warm_slack_auth_cache(_slack_app.client)
    _socket_handler = AsyncSocketModeHandler(_slack_app, settings.slack_app_token)
    set_handler(_socket_handler)
    try:
        await _socket_handler.connect_async()
        logger.info("Slack Socket Mode connected")
        return True
    except Exception:
        logger.exception("Slack Socket Mode connection failed")
        from tempa.channels.slack.session import set_error

        set_error("Socket Mode connection failed")
        _socket_handler = None
        _slack_app = None
        set_handler(None)
        return False


async def stop_slack_socket_mode() -> None:
    global _slack_app, _socket_handler, _slack_auth_cache
    handler = _socket_handler
    _socket_handler = None
    _slack_app = None
    _slack_auth_cache = None
    set_handler(None)
    if handler is not None:
        try:
            await handler.close_async()
        except Exception:
            logger.exception("Slack Socket Mode shutdown failed")
