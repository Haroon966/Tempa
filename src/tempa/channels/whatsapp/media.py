from __future__ import annotations

import base64
import logging
import tempfile
from pathlib import Path
from typing import Any

import httpx

from tempa.channels.whatsapp.client import WhatsAppBridgeClient
from tempa.router.groq_router import get_router

logger = logging.getLogger(__name__)


async def transcribe_whatsapp_audio(message_item: dict[str, Any]) -> str:
    """FR-WA-06: transcribe voice notes via Groq Whisper."""
    client = WhatsAppBridgeClient()
    payload = {"message": message_item}
    async with httpx.AsyncClient(timeout=60) as http:
        resp = await http.post(
            f"{client.base_url}/chat/getBase64FromMediaMessage/{client.instance}",
            json=payload,
            headers=client._headers(),
        )
        if resp.status_code >= 400:
            logger.warning("Media download failed: %s", resp.status_code)
            return ""
        data = resp.json()
    b64 = data.get("base64") or data.get("data", {}).get("base64")
    if not b64:
        return ""
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    audio_bytes = base64.b64decode(b64)
    tmp = Path(tempfile.gettempdir()) / f"tempa-wa-{message_item.get('key', {}).get('id', 'voice')}.ogg"
    tmp.write_bytes(audio_bytes)
    try:
        return get_router().transcribe_file(tmp)
    except Exception:
        logger.exception("Voice transcription failed")
        return ""
    finally:
        tmp.unlink(missing_ok=True)
