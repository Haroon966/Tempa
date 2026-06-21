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
    assert extract_recipient("Send recipient@example.com a mail") == ""


def test_rejects_placeholder_emails():
    from tempa.channels.gmail.compose import (
        is_placeholder_email,
        is_valid_recipient_email,
        validate_recipient_email,
    )

    assert is_placeholder_email("recipient@example.com") is True
    assert is_placeholder_email("test@example.com") is True
    assert is_valid_recipient_email("haroon@gmail.com") is True
    ok, err = validate_recipient_email("user@example.com")
    assert ok is False
    assert "placeholder" in err.lower()


def test_resolve_email_recipient_prefers_real_address():
    from tempa.channels.gmail.compose import resolve_email_recipient

    resolved = resolve_email_recipient(
        task="Send haroon@gmail.com an update about Tempa",
        user_message="",
        llm_to="recipient@example.com",
    )
    assert resolved == "haroon@gmail.com"


def test_resolve_email_recipient_rejects_placeholder_only():
    from tempa.channels.gmail.compose import resolve_email_recipient

    assert resolve_email_recipient(task="Send an update", llm_to="recipient@example.com") == ""


def test_wants_html_email():
    from tempa.channels.gmail.compose import wants_html_email

    assert wants_html_email("beautiful html mail") is True
    assert wants_html_email("plain email") is False


def test_build_html_email_neutral_layout():
    from tempa.channels.gmail.compose import build_html_email

    html_out = build_html_email(
        headline="Order confirmed",
        body_plain="Your order is on the way.",
        detail_labels=["Order", "Status"],
        detail_values=["#12345", "Shipped"],
        cta_url="https://example.com/order/12345",
        cta_label="Track order",
    )
    assert "Order confirmed" in html_out
    assert "Your order is on the way." in html_out
    assert "#12345" in html_out
    assert "Track order" in html_out
    assert "#2F5FFF" not in html_out
    assert "email-container" in html_out


def test_finalize_beautiful_email_wraps_plain_draft():
    from tempa.channels.gmail.compose import finalize_beautiful_email, is_beautiful_email_html

    draft = finalize_beautiful_email(
        {
            "to": "haroon@gmail.com",
            "subject": "Tempa is Up and Running!",
            "body": "Dear Haroon, Tempa is now fully operational.",
            "closing_text": "Thank you for your continued support.",
            "signature": "Warm regards, Tempa",
        }
    )
    assert is_beautiful_email_html(draft["body_html"])
    assert "Tempa is Up and Running!" in draft["body_html"]
    assert "Dear Haroon" in draft["body_html"]
    assert "Warm regards, Tempa" in draft["body"]
    assert "MESSAGE" in draft["body_html"]


def test_finalize_beautiful_email_replaces_weak_html():
    from tempa.channels.gmail.compose import finalize_beautiful_email

    draft = finalize_beautiful_email(
        {
            "subject": "Hello",
            "body": "Plain body only.",
            "body_html": "<p>weak html</p>",
        }
    )
    assert "email-container" in draft["body_html"]
    assert "Plain body only." in draft["body_html"]


def test_default_html_template_uses_neutral_builder():
    from tempa.channels.gmail.compose import _default_html_template

    html_out = _default_html_template(subject="Hello", body_plain="Line one\nLine two", recipient="a@b.com")
    assert "Hello" in html_out
    assert "Line one" in html_out
    assert "Line two" in html_out
    assert "email-container" in html_out
    assert "#0f766e" not in html_out.lower()
