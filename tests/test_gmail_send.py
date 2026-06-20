import json

from tempa.router.safety import screen_outbound_message


def test_safety_allows_plain_email():
    allowed, reason = screen_outbound_message(
        "To: test@example.com\nSubject: Hello\n\nThis is a friendly note."
    )
    assert allowed is True
    assert reason


def test_whatsapp_gmail_reply_blocked_reason_fallback():
    from tempa.agents.specialists import _whatsapp_gmail_reply

    reply = _whatsapp_gmail_reply(json.dumps({"status": "blocked", "reason": ""}))
    assert "safety" in reply.lower() or "blocked" in reply.lower()


def test_extract_recipient():
    from tempa.channels.gmail.compose import extract_recipient

    assert extract_recipient("Send maavia.qureshi@gmail.com a beautiful html mail") == (
        "maavia.qureshi@gmail.com"
    )


def test_wants_html_email():
    from tempa.channels.gmail.compose import wants_html_email

    assert wants_html_email("beautiful html mail") is True
    assert wants_html_email("plain email") is False
