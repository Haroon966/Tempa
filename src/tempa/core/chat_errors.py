from __future__ import annotations

from typing import Any


class ChatError(Exception):
    def __init__(self, code: str, message: str, *, recoverable: bool = True) -> None:
        self.code = code
        self.message = message
        self.recoverable = recoverable
        super().__init__(message)

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": self.message,
            "code": self.code,
            "recoverable": self.recoverable,
        }


def classify_exception(exc: Exception) -> dict[str, Any]:
    text = str(exc).lower()
    if "groq" in text or "api key" in text:
        return ChatError("GROQ_UNAVAILABLE", "Groq API is unavailable — check your API key in Connections.").to_payload()
    if "gmail" in text and "not connected" in text:
        return ChatError("GMAIL_NOT_CONNECTED", "Gmail is not connected — connect in Connections.").to_payload()
    if "calendar" in text and "not connected" in text:
        return ChatError("CALENDAR_NOT_CONNECTED", "Google Calendar is not connected.").to_payload()
    if "whatsapp" in text and ("disconnect" in text or "qr" in text):
        return ChatError("WHATSAPP_DISCONNECTED", "WhatsApp disconnected — scan QR in Connections.").to_payload()
    if "timeout" in text or "timed out" in text:
        return ChatError("TIMEOUT", "Request timed out — please try again.").to_payload()
    if "cancel" in text:
        return ChatError("CANCELLED", "Run cancelled.", recoverable=False).to_payload()
    return ChatError("UNKNOWN", str(exc) or "An unexpected error occurred.").to_payload()
