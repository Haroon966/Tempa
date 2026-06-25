"""Outbound (fromMe) WhatsApp messages are recorded for conversation summaries."""

from tempa.channels.whatsapp.schemas import parse_outbound_messages_upsert


def test_parse_outbound_messages_upsert():
    payload = {
        "data": {
            "key": {
                "remoteJid": "923006081744@s.whatsapp.net",
                "fromMe": True,
                "id": "OUT1",
            },
            "message": {"conversation": "Salam, package details bhej raha hoon."},
            "messageTimestamp": 1782385000,
        }
    }
    parsed = parse_outbound_messages_upsert(payload)
    assert len(parsed) == 1
    assert parsed[0].text == "Salam, package details bhej raha hoon."
    assert parsed[0].chat_id == "923006081744@s.whatsapp.net"
    assert parsed[0].from_number == "923006081744"


def test_parse_outbound_skips_inbound():
    payload = {
        "data": {
            "key": {
                "remoteJid": "923006081744@s.whatsapp.net",
                "fromMe": False,
                "id": "IN1",
            },
            "message": {"conversation": "customer msg"},
        }
    }
    assert parse_outbound_messages_upsert(payload) == []
