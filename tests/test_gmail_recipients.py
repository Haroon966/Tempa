from tempa.channels.gmail.recipients import (
    build_gmail_search_queries,
    extract_recipient_name,
    lookup_email_by_name_in_gmail,
)


def test_extract_recipient_name_from_send_request():
    assert extract_recipient_name("send mail to Haroon Ali about Tempa") == "Haroon Ali"
    assert extract_recipient_name("email Haroon Ali that Tempa is ready") == "Haroon Ali"
    assert extract_recipient_name("send Haroon Ali an email about the launch") == "Haroon Ali"


def test_build_gmail_search_queries_includes_name_variants():
    queries = build_gmail_search_queries("Haroon Ali")
    assert '"Haroon Ali"' in queries
    assert "from:Haroon Ali" in queries
    assert "to:Haroon Ali" in queries
    assert "from:Haroon" in queries


def test_lookup_email_by_name_in_gmail(monkeypatch):
    from tempa.channels.gmail import recipients as mod

    class FakeMessage:
        def __init__(self, sender: str, to: str):
            self.sender = sender
            self.to = to

    class FakeClient:
        def list_messages(self, *, query: str, max_results: int):
            if "Haroon" in query:
                return (["m1", "m2"], None)
            return ([], None)

        def get_message_metadata(self, message_id: str):
            if message_id == "m1":
                return FakeMessage('"Haroon Ali" <haroon.ali@gmail.com>', "me@company.com")
            return FakeMessage("me@company.com", "Haroon Ali <haroon.ali@gmail.com>")

    monkeypatch.setattr(mod, "load_gmail_client", lambda: FakeClient())

    hit = lookup_email_by_name_in_gmail("Haroon Ali")
    assert hit["email"] == "haroon.ali@gmail.com"
    assert hit["source"] == "gmail"


def test_resolve_email_recipient_prefers_gmail_history(monkeypatch):
    from tempa.channels.gmail.compose import resolve_email_recipient

    resolved = resolve_email_recipient(
        task="send mail to Haroon Ali about Tempa",
        gmail_hint={"email": "haroon.ali@gmail.com", "name": "Haroon Ali"},
        llm_to="recipient@example.com",
    )
    assert resolved == "haroon.ali@gmail.com"
