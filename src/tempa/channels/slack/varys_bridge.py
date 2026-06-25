from __future__ import annotations

from typing import Any

from tempa.varys.manager import is_go_signal, is_work_request


def classify_slack_message(text: str, *, user_id: str, owner_user_id: str) -> str:
    if owner_user_id and user_id == owner_user_id and is_go_signal(text):
        return "go_signal"
    if is_work_request(text):
        return "work_request"
    return "conversational"


def enrich_slack_context(event: dict, base: dict[str, Any]) -> dict[str, Any]:
    ctx = dict(base)
    ctx["channel"] = "slack"
    ctx["slack_user_id"] = str(event.get("user") or "")
    ctx["slack_channel_id"] = str(event.get("channel") or "")
    message_ts = str(event.get("ts") or "")
    thread_ts = str(event.get("thread_ts") or message_ts)
    ctx["slack_thread_ts"] = thread_ts if event.get("thread_ts") or event.get("channel_type") == "im" else ""
    ctx["thread_ts"] = thread_ts
    ctx["inbound_slack"] = True
    return ctx
