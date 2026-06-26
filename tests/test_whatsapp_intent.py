from tempa.channels.whatsapp.intent import WhatsAppIntent, route_whatsapp_intent


def test_route_gmail_intent():
    assert route_whatsapp_intent("any mail from hostinger") == WhatsAppIntent.GMAIL


def test_route_calendar_invite_not_gmail():
    text = "send an invite of meeting name haroon x tempa to haroon.ali@taleemabad at 6:40pm today"
    assert route_whatsapp_intent(text) == WhatsAppIntent.CALENDAR


def test_route_meet_join_intent():
    url = "https://meet.google.com/abc-defg-hij"
    assert route_whatsapp_intent(f"join {url}") == WhatsAppIntent.MEET_JOIN


def test_route_status_followup():
    assert route_whatsapp_intent("why") == WhatsAppIntent.ACTION_STATUS_FOLLOWUP
    assert route_whatsapp_intent("resend") == WhatsAppIntent.ACTION_STATUS_FOLLOWUP


def test_route_pc_coordinator():
    assert route_whatsapp_intent("open vscode please") == WhatsAppIntent.COORDINATOR


def test_route_chat_default():
    assert route_whatsapp_intent("hello there") == WhatsAppIntent.CHAT


def test_github_url_routes_to_coordinator():
    text = "https://github.com/Haroon966/Wavo scan this repo"
    assert route_whatsapp_intent(text) == WhatsAppIntent.COORDINATOR
