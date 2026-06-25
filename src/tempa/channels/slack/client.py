from __future__ import annotations

import logging
from typing import Any, Iterator

from slack_sdk.errors import SlackApiError

from tempa.settings import get_settings

logger = logging.getLogger(__name__)

DEFAULT_CONVERSATION_TYPES = "public_channel,im"


def load_slack_client():
    from slack_sdk import WebClient

    token = get_settings().slack_bot_token.strip()
    if not token:
        return None
    return WebClient(token=token)


def auth_test(client) -> dict[str, Any]:
    return client.auth_test().data


def _list_conversations_for_type(
    client,
    *,
    conv_type: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    channels: list[dict[str, Any]] = []
    cursor = None
    while len(channels) < limit:
        kwargs: dict[str, Any] = {"types": conv_type, "limit": min(200, limit - len(channels))}
        if cursor:
            kwargs["cursor"] = cursor
        response = client.conversations_list(**kwargs)
        channels.extend(response.get("channels") or [])
        cursor = (response.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return channels


def list_conversations(
    client,
    *,
    types: str = DEFAULT_CONVERSATION_TYPES,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List Slack conversations, skipping types the bot token lacks scopes for."""
    type_list = [t.strip() for t in types.split(",") if t.strip()]
    channels: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for conv_type in type_list:
        try:
            batch = _list_conversations_for_type(client, conv_type=conv_type, limit=limit)
        except SlackApiError as exc:
            err = ""
            needed = conv_type
            if exc.response is not None:
                err = str(exc.response.get("error") or "")
                needed = str(exc.response.get("needed") or conv_type)
            if err == "missing_scope":
                logger.warning(
                    "Slack conversations.list skipped type=%s (add OAuth scope %s to sync these)",
                    conv_type,
                    needed,
                )
                continue
            raise

        for channel in batch:
            channel_id = str(channel.get("id") or "")
            if channel_id and channel_id not in seen_ids:
                seen_ids.add(channel_id)
                channels.append(channel)

    return channels


def iter_conversation_messages(
    client,
    channel_id: str,
    *,
    oldest: str = "",
    limit: int = 200,
) -> Iterator[dict[str, Any]]:
    fetched = 0
    cursor = None
    while fetched < limit:
        page_limit = min(200, limit - fetched)
        kwargs: dict[str, Any] = {"channel": channel_id, "limit": page_limit}
        if oldest:
            kwargs["oldest"] = oldest
        if cursor:
            kwargs["cursor"] = cursor
        response = client.conversations_history(**kwargs)
        messages = list(response.get("messages") or [])
        if not messages:
            break
        for msg in messages:
            yield msg
            fetched += 1
            if fetched >= limit:
                return
        cursor = (response.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break


def iter_thread_replies(
    client,
    channel_id: str,
    thread_ts: str,
    *,
    limit: int = 100,
) -> Iterator[dict[str, Any]]:
    fetched = 0
    cursor = None
    while fetched < limit:
        page_limit = min(200, limit - fetched)
        kwargs: dict[str, Any] = {
            "channel": channel_id,
            "ts": thread_ts,
            "limit": page_limit,
        }
        if cursor:
            kwargs["cursor"] = cursor
        response = client.conversations_replies(**kwargs)
        messages = list(response.get("messages") or [])
        if not messages:
            break
        for msg in messages:
            if msg.get("ts") == thread_ts:
                continue
            yield msg
            fetched += 1
            if fetched >= limit:
                return
        cursor = (response.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break


def list_users(client, *, limit: int = 5000) -> list[dict[str, Any]]:
    users: list[dict[str, Any]] = []
    cursor = None
    while len(users) < limit:
        kwargs: dict[str, Any] = {"limit": min(200, limit - len(users))}
        if cursor:
            kwargs["cursor"] = cursor
        response = client.users_list(**kwargs)
        users.extend(response.get("members") or [])
        cursor = (response.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return users


def user_display_name(user: dict[str, Any]) -> str:
    profile = user.get("profile") or {}
    return (
        profile.get("display_name")
        or profile.get("real_name")
        or user.get("name")
        or user.get("id")
        or "unknown"
    )


def find_dm_channel(client, user_id: str) -> str:
    for channel in list_conversations(client, types="im", limit=200):
        if str(channel.get("user") or "") == user_id:
            return str(channel.get("id") or "")
    return ""


def open_dm_channel(client, user_id: str) -> str:
    existing = find_dm_channel(client, user_id)
    if existing:
        return existing
    response = client.conversations_open(users=user_id)
    channel = response.get("channel") or {} if isinstance(response, dict) else {}
    if hasattr(response, "get"):
        channel = response.get("channel") or {}
    else:
        channel = getattr(response, "data", {}).get("channel") or {}
    channel_id = str(channel.get("id") or "")
    if not channel_id:
        raise ValueError(f"Could not open DM with user {user_id}")
    return channel_id
