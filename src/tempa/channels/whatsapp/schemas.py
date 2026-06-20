from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WhatsAppMessage(BaseModel):
    from_number: str = Field(alias="from")
    text: str
    message_id: str = ""
    timestamp: int | None = None
    chat_id: str = ""
    is_group: bool = False
    raw_item: dict[str, Any] = Field(default_factory=dict)


class EvolutionWebhookPayload(BaseModel):
    event: str
    instance: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


def _extract_text(message: dict[str, Any]) -> str:
    return (
        message.get("conversation")
        or message.get("extendedTextMessage", {}).get("text")
        or message.get("imageMessage", {}).get("caption")
        or message.get("documentMessage", {}).get("caption")
        or ""
    )


def parse_messages_upsert(payload: dict[str, Any]) -> list[WhatsAppMessage]:
    messages: list[WhatsAppMessage] = []
    data = payload.get("data", payload)
    items = data.get("messages")
    if items is None:
        # Evolution API v2 sends a single message object in `data` with top-level `key`.
        if isinstance(data, dict) and "key" in data:
            items = [data]
        else:
            nested = data.get("message")
            items = [nested] if isinstance(nested, dict) else []
    if isinstance(items, dict):
        items = [items]
    for item in items:
        if not isinstance(item, dict):
            continue
        key = item.get("key", {})
        if key.get("fromMe"):
            continue
        remote_jid = key.get("remoteJid", "") or key.get("remoteJidAlt", "")
        is_group = remote_jid.endswith("@g.us")
        participant = key.get("participant", "") or key.get("participantAlt", "")
        from_number = (
            participant.split("@")[0]
            if participant
            else remote_jid.split("@")[0] if remote_jid else ""
        )
        message = item.get("message", item)
        text = _extract_text(message if isinstance(message, dict) else {})
        has_audio = bool(isinstance(message, dict) and message.get("audioMessage"))
        if not text and not has_audio:
            continue
        messages.append(
            WhatsAppMessage(
                **{
                    "from": from_number or remote_jid.split("@")[0],
                    "text": text or "[voice note]",
                    "message_id": key.get("id", ""),
                    "timestamp": item.get("messageTimestamp"),
                    "chat_id": remote_jid,
                    "is_group": is_group,
                    "raw_item": item,
                }
            )
        )
    return messages
