from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from tempa.api.app import create_app
from tempa.channels.whatsapp.webhook import get_recent_messages


def test_whatsapp_webhook_ingest():
    app = create_app()
    client = TestClient(app)
    payload = {
        "event": "messages.upsert",
        "data": {
            "messages": [
                {
                    "key": {"remoteJid": "15551234567@s.whatsapp.net", "id": "abc"},
                    "message": {"conversation": "integration hello"},
                }
            ]
        },
    }
    with patch("asyncio.create_task") as mock_create_task:
        res = client.post("/webhooks/whatsapp", json=payload)
        assert res.status_code == 200
        assert res.json()["status"] == "accepted"
        mock_create_task.assert_called_once()


def test_whatsapp_webhook_evolution_v2_single_message():
    from tempa.channels.whatsapp.schemas import parse_messages_upsert

    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "remoteJid": "923435971748@s.whatsapp.net",
                "fromMe": False,
                "id": "msg-1",
            },
            "message": {"conversation": "Hi"},
            "messageTimestamp": 1781607106,
        },
    }
    parsed = parse_messages_upsert(payload)
    assert len(parsed) == 1
    assert parsed[0].text == "Hi"
    assert parsed[0].from_number == "923435971748"
