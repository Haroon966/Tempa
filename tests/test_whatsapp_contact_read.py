import json
from unittest.mock import AsyncMock, patch

import pytest

from tempa.agents import specialists as sp


def test_extract_whatsapp_contact_query():
    assert sp._extract_whatsapp_contact_query("check zeeshan latest message") == "zeeshan"
    assert sp._extract_whatsapp_contact_query("message from ali") == "ali"


def test_extract_phone_handles_spaced_international():
    from tempa.channels.whatsapp.history import _extract_phone, _format_phone_display

    assert _extract_phone("+92 331 3115516") == "923313115516"
    assert _format_phone_display("923313115516") == "+92 331 3115516"


def test_whatsapp_read_reply_skips_unrelated_recent_messages():
    payload = json.dumps({"status": "ok", "recent_messages": [{"text": "wrong person"}]})
    assert sp._whatsapp_read_reply(payload, "check zeeshan message") is None


def test_whatsapp_read_reply_formats_thread():
    payload = json.dumps(
        {
            "status": "ok",
            "contact": "Zeeshan",
            "latest_message": "Ok hy",
            "timestamp": "2026-07-03T18:00:00+00:00",
            "messages": [
                {"from": "Zeeshan", "text": "Hello", "role": "user"},
                {"from": "you", "text": "Hi", "role": "assistant"},
                {"from": "Zeeshan", "text": "Ok hy", "role": "user"},
            ],
        }
    )
    reply = sp._whatsapp_read_reply(payload, "summarize zeeshan message")
    assert reply is not None
    assert "Zeeshan" in reply
    assert "Ok hy" in reply
    assert "Hello" in reply


@pytest.mark.asyncio
async def test_lookup_uses_local_conversation_history(tmp_path, monkeypatch):
    wa_dir = tmp_path / "whatsapp"
    wa_dir.mkdir()
    (wa_dir / "conversation.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "role": "user",
                        "from": "923356974965",
                        "text": "Ok hy",
                        "chat_id": "923356974965@s.whatsapp.net",
                        "timestamp": "2026-07-03T18:00:00+00:00",
                    }
                ),
                json.dumps(
                    {
                        "role": "user",
                        "from": "923356974965",
                        "text": "Earlier note",
                        "chat_id": "923356974965@s.whatsapp.net",
                        "timestamp": "2026-07-03T17:00:00+00:00",
                    }
                ),
            ]
        )
    )
    (wa_dir / "name_aliases.json").write_text(json.dumps({"zeeshan": "923356974965"}))

    monkeypatch.setattr("tempa.settings.get_settings", lambda: type("S", (), {"sessions_dir": tmp_path})())

    with patch(
        "tempa.channels.whatsapp.client.WhatsAppBridgeClient.fetch_contact_history",
        new_callable=AsyncMock,
        return_value={"contact": "Zeeshan", "jid": "923356974965@s.whatsapp.net", "messages": []},
    ), patch(
        "tempa.channels.whatsapp.client.WhatsAppBridgeClient.match_contacts",
        new_callable=AsyncMock,
        return_value=[],
    ):
        from tempa.channels.whatsapp.history import lookup_contact_messages

        result = await lookup_contact_messages("zeeshan")
    assert result["latest_message"] == "Ok hy"
    assert len(result["messages"]) == 2
    assert result["source"] == "whatsapp_history"


@pytest.mark.asyncio
async def test_chat_phone_fallback_finds_history(tmp_path, monkeypatch):
    wa_dir = tmp_path / "whatsapp"
    wa_dir.mkdir()
    (wa_dir / "name_aliases.json").write_text(
        json.dumps({"zeeshan": "923313115516", "zeeshan__chat": "923356974965"})
    )
    (wa_dir / "conversation.jsonl").write_text(
        json.dumps(
            {
                "role": "user",
                "from": "923356974965",
                "text": "By",
                "chat_id": "923356974965@s.whatsapp.net",
                "timestamp": "2026-07-03T18:05:37.198347+00:00",
            }
        )
    )
    monkeypatch.setattr("tempa.settings.get_settings", lambda: type("S", (), {"sessions_dir": tmp_path})())

    with patch(
        "tempa.channels.whatsapp.client.WhatsAppBridgeClient.fetch_contact_history",
        new_callable=AsyncMock,
        return_value={"contact": "Zeeshan", "jid": "923356974965@s.whatsapp.net", "messages": []},
    ), patch(
        "tempa.channels.whatsapp.client.WhatsAppBridgeClient.match_contacts",
        new_callable=AsyncMock,
        return_value=[],
    ):
        from tempa.channels.whatsapp.history import lookup_contact_messages

        result = await lookup_contact_messages("zeeshan")
    assert result["phone"] == "923313115516"
    assert result["chat_phone"] == "923356974965"
    assert result["latest_message"] == "By"


@pytest.mark.asyncio
async def test_alias_overrides_stale_peer(tmp_path, monkeypatch):
    wa_dir = tmp_path / "whatsapp"
    wa_dir.mkdir()
    (wa_dir / "name_aliases.json").write_text(json.dumps({"zeeshan": "923313115516"}))
    (wa_dir / "peers.json").write_text(
        json.dumps(
            {
                "zeeshan": {
                    "push_name": "zeeshan",
                    "jid": "138517678174277@lid",
                    "phone": "923356974965",
                }
            }
        )
    )

    monkeypatch.setattr("tempa.settings.get_settings", lambda: type("S", (), {"sessions_dir": tmp_path})())

    with patch(
        "tempa.channels.whatsapp.client.WhatsAppBridgeClient.fetch_contact_history",
        new_callable=AsyncMock,
        return_value={"contact": "Zeeshan", "jid": "923313115516@s.whatsapp.net", "messages": []},
    ), patch(
        "tempa.channels.whatsapp.client.WhatsAppBridgeClient.match_contacts",
        new_callable=AsyncMock,
        return_value=[],
    ):
        from tempa.channels.whatsapp.history import lookup_contact_messages

        result = await lookup_contact_messages("zeeshan")
    assert result["phone"] == "923313115516"
