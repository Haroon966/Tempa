from __future__ import annotations

from typing import Any

from tempa.channels.slack.conversation import conversation_thread_key
from tempa.varys.manager import is_go_signal, is_work_request


def classify_slack_message(text: str, *, user_id: str, owner_user_id: str) -> str:
    if owner_user_id and user_id == owner_user_id and is_go_signal(text):
        return "go_signal"
    if is_work_request(text):
        return "work_request"
    return "conversational"


def enrich_slack_context(event: dict, base: dict[str, Any]) -> dict[str, Any]:
    from tempa.channels.slack.context import is_dm_event, thread_root

    ctx = dict(base)
    ctx["channel"] = "slack"
    ctx["slack_user_id"] = str(event.get("user") or "")
    ctx["slack_channel_id"] = str(event.get("channel") or "")
    is_dm = is_dm_event(event)
    root = thread_root(event)
    ctx["slack_is_dm"] = is_dm
    ctx["slack_thread_ts"] = root
    ctx["thread_ts"] = root
    ctx["slack_conversation_key"] = conversation_thread_key(
        channel_id=ctx["slack_channel_id"],
        thread_ts=root,
        is_dm=is_dm,
    )
    ctx["inbound_slack"] = True
    return ctx
