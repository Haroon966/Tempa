import pytest


@pytest.mark.asyncio
async def test_mark_messages_as_read_payload():
    from unittest.mock import AsyncMock, MagicMock, patch

    raw_item = {
        "key": {
            "remoteJid": "72134512668711@lid",
            "fromMe": False,
            "id": "ABC123",
        }
    }

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"read": "success"}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("tempa.channels.whatsapp.client.httpx.AsyncClient", return_value=mock_cm):
        from tempa.channels.whatsapp.client import WhatsAppBridgeClient

        result = await WhatsAppBridgeClient().mark_messages_as_read(raw_item)

    assert result["read"] == "success"
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["readMessages"][0]["remoteJid"] == "72134512668711@lid"
    assert payload["readMessages"][0]["id"] == "ABC123"
