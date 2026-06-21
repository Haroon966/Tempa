from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_transcribe_whatsapp_audio_uses_groq():
    from tempa.channels.whatsapp.media import transcribe_whatsapp_audio

    raw_item = {
        "key": {"id": "msg1"},
        "message": {
            "audioMessage": {
                "url": "https://example.com/audio.ogg",
                "mimetype": "audio/ogg",
            }
        },
    }

    with (
        patch("tempa.channels.whatsapp.media.httpx.AsyncClient") as client_cls,
        patch("tempa.channels.whatsapp.media.get_router") as get_router,
        patch("tempa.channels.whatsapp.media.WhatsAppBridgeClient") as client_ctor,
    ):
        evo = MagicMock()
        evo.base_url = "http://evolution"
        evo.instance = "inst"
        evo._headers.return_value = {"apikey": "key"}
        client_ctor.return_value = evo

        http = AsyncMock()
        http.post.return_value = MagicMock(status_code=200, json=lambda: {"base64": "YWJj"})
        http.__aenter__.return_value = http
        http.__aexit__.return_value = None
        client_cls.return_value = http

        router = MagicMock()
        router.transcribe_file.return_value = "Schedule a meeting at 5pm"
        get_router.return_value = router

        text = await transcribe_whatsapp_audio(raw_item)

    assert text == "Schedule a meeting at 5pm"
    router.transcribe_file.assert_called_once()


def test_resolve_message_text_transcribes_voice_notes():
    import asyncio

    from tempa.channels.whatsapp import reply as reply_mod

    async def run():
        with patch(
            "tempa.channels.whatsapp.reply.transcribe_whatsapp_audio",
            new_callable=AsyncMock,
            return_value="hello from voice",
        ):
            text = await reply_mod._resolve_message_text(
                "[voice note]",
                {"message": {"audioMessage": {"url": "https://x/a.ogg"}}},
            )
            return text

    assert asyncio.run(run()) == "hello from voice"
