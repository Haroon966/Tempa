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


def _unwrap_message(message: dict[str, Any] | None) -> dict[str, Any]:
    """Unwrap ephemeral/view-once wrappers (ponytail: max 5 hops like baileys)."""
    if not isinstance(message, dict):
        return {}
    current: dict[str, Any] = message
    for _ in range(5):
        inner = None
        for key in (
            "ephemeralMessage",
            "viewOnceMessage",
            "viewOnceMessageV2",
            "viewOnceMessageV2Extension",
            "documentWithCaptionMessage",
            "editedMessage",
        ):
            wrapped = current.get(key)
            if isinstance(wrapped, dict) and isinstance(wrapped.get("message"), dict):
                inner = wrapped["message"]
                break
        if not inner:
            break
        current = inner
    return current


def _extract_text(message: dict[str, Any]) -> str:
    msg = _unwrap_message(message)
    return (
        msg.get("conversation")
        or msg.get("extendedTextMessage", {}).get("text")
        or msg.get("imageMessage", {}).get("caption")
        or msg.get("documentMessage", {}).get("caption")
        or ""
    )


def _has_audio(message: dict[str, Any]) -> bool:
    return bool(_unwrap_message(message).get("audioMessage"))


def _iter_messages_upsert_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", payload)
    items = data.get("messages")
    if items is None:
        if isinstance(data, dict) and "key" in data:
            items = [data]
        else:
            nested = data.get("message")
            items = [nested] if isinstance(nested, dict) else []
    if isinstance(items, dict):
        items = [items]
    return [item for item in items if isinstance(item, dict)]


def _effective_jid(key: dict[str, Any]) -> tuple[str, bool]:
    remote_jid = key.get("remoteJid", "") or ""
    alt_jid = key.get("remoteJidAlt", "") or key.get("participantAlt", "") or ""
    if remote_jid.endswith("@lid") and alt_jid:
        effective_jid = alt_jid
    else:
        effective_jid = remote_jid or alt_jid
    is_group = effective_jid.endswith("@g.us")
    return effective_jid or remote_jid, is_group


def parse_messages_upsert(payload: dict[str, Any]) -> list[WhatsAppMessage]:
    messages: list[WhatsAppMessage] = []
    for item in _iter_messages_upsert_items(payload):
        key = item.get("key", {})
        if key.get("fromMe"):
            continue
        effective_jid, is_group = _effective_jid(key)
        participant = key.get("participant", "") or key.get("participantAlt", "")
        from_number = (
            participant.split("@")[0].split(":")[0]
            if participant
            else effective_jid.split("@")[0].split(":")[0] if effective_jid else ""
        )
        message = item.get("message", item)
        if not isinstance(message, dict):
            continue
        text = _extract_text(message)
        if not text and not _has_audio(message):
            continue
        messages.append(
            WhatsAppMessage(
                **{
                    "from": from_number or effective_jid.split("@")[0].split(":")[0],
                    "text": text or "[voice note]",
                    "message_id": key.get("id", ""),
                    "timestamp": item.get("messageTimestamp"),
                    "chat_id": effective_jid,
                    "is_group": is_group,
                    "raw_item": item,
                }
            )
        )
    return messages


def parse_outbound_messages_upsert(payload: dict[str, Any]) -> list[WhatsAppMessage]:
    """Messages sent from the linked WhatsApp account (fromMe)."""
    messages: list[WhatsAppMessage] = []
    for item in _iter_messages_upsert_items(payload):
        key = item.get("key", {})
        if not key.get("fromMe"):
            continue
        effective_jid, is_group = _effective_jid(key)
        if is_group:
            continue
        message = item.get("message", item)
        if not isinstance(message, dict):
            continue
        text = _extract_text(message)
        if not text and not _has_audio(message):
            continue
        peer = effective_jid.split("@")[0].split(":")[0] if effective_jid else ""
        messages.append(
            WhatsAppMessage(
                **{
                    "from": peer,
                    "text": text or "[voice note]",
                    "message_id": key.get("id", ""),
                    "timestamp": item.get("messageTimestamp"),
                    "chat_id": effective_jid,
                    "is_group": False,
                    "raw_item": item,
                }
            )
        )
    return messages
