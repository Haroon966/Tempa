from tempa.channels.whatsapp.schemas import _has_audio, parse_messages_upsert


def test_parse_ephemeral_wrapped_voice_note():
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "remoteJid": "923001234567@s.whatsapp.net",
                "fromMe": False,
                "id": "voice-1",
            },
            "pushName": "Zeeshan Qureshi",
            "message": {
                "ephemeralMessage": {
                    "message": {
                        "audioMessage": {
                            "mimetype": "audio/ogg; codecs=opus",
                            "seconds": 12,
                        }
                    }
                }
            },
            "messageTimestamp": 1782978675,
        },
    }
    assert _has_audio(payload["data"]["message"])
    parsed = parse_messages_upsert(payload)
    assert len(parsed) == 1
    assert parsed[0].text == "[voice note]"
    assert parsed[0].from_number == "923001234567"
