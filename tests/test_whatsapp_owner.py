import pytest

from tempa.channels.whatsapp.numbers import normalize_phone, phones_match


def test_normalize_pakistan_local_number():
    assert normalize_phone("03435971748") == "923435971748"
    assert normalize_phone("923435971748") == "923435971748"
    assert phones_match("03435971748", "923435971748")


@pytest.mark.asyncio
async def test_ingest_all_reply_owner_only(monkeypatch):
    monkeypatch.setenv("WHATSAPP_OWNER_NUMBER", "03435971748")
    from tempa.settings import get_settings

    get_settings.cache_clear()

    from unittest.mock import AsyncMock, patch

    with (
        patch("tempa.channels.whatsapp.reply.is_auto_reply_paused", return_value=False),
        patch("tempa.channels.whatsapp.reply.run_whatsapp_reply", new_callable=AsyncMock, return_value="ok") as reply_fn,
        patch("tempa.channels.whatsapp.reply.asyncio.create_task"),
        patch("tempa.channels.whatsapp.reply.event_bus.publish_json", new_callable=AsyncMock),
    ):
        from tempa.channels.whatsapp.reply import handle_inbound_whatsapp

        other = await handle_inbound_whatsapp("15551234567", "hello from other", "m1")
        assert other["ingested"] is True
        assert other["skipped_reply"] is True
        reply_fn.assert_not_called()

        owner = await handle_inbound_whatsapp("923435971748", "hello owner", "m2")
        assert owner["handled"] == 1
        reply_fn.assert_awaited_once()

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_reply_allowed_for_extra_numbers(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WHATSAPP_OWNER_NUMBER", "03435971748")
    from tempa.settings import get_settings

    get_settings.cache_clear()

    from tempa.channels.whatsapp.numbers import set_extra_allowed_whatsapp_numbers

    set_extra_allowed_whatsapp_numbers(["03001234567"])

    from unittest.mock import AsyncMock, patch

    with (
        patch("tempa.channels.whatsapp.reply.is_auto_reply_paused", return_value=False),
        patch("tempa.channels.whatsapp.reply.run_whatsapp_reply", new_callable=AsyncMock, return_value="ok") as reply_fn,
        patch("tempa.channels.whatsapp.reply.send_whatsapp_message", new_callable=AsyncMock, return_value={"status": "ok"}),
        patch("tempa.channels.whatsapp.reply.asyncio.create_task"),
        patch("tempa.channels.whatsapp.reply.event_bus.publish_json", new_callable=AsyncMock),
    ):
        from tempa.channels.whatsapp.reply import handle_inbound_whatsapp

        other = await handle_inbound_whatsapp("15551234567", "hello from other", "m3")
        assert other["skipped_reply"] is True
        reply_fn.assert_not_called()

        extra = await handle_inbound_whatsapp("923001234567", "hello extra", "m4")
        assert extra["handled"] == 1
        reply_fn.assert_awaited_once()

    get_settings.cache_clear()
