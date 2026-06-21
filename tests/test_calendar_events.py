from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from tempa.channels.calendar.events import (
    format_calendar_error,
    parse_attendee_emails,
    parse_delete_title,
    parse_event_duration,
    parse_event_start,
    parse_event_time_range,
    parse_event_title,
    try_create_event_from_message,
    try_delete_event_from_message,
    try_invite_guests_from_message,
    wants_create_event,
    wants_delete_event,
)


def test_wants_create_event():
    assert wants_create_event("make a meeting on calendar around 5:10pm name tempa testing")
    assert wants_create_event(
        "send an invite of meeting name haroon x tempa to haroon.ali@taleemabad at 6:40pm today"
    )
    assert wants_create_event("set a meeting me and haroon ali at 11:30pm to 11:45pm today")
    assert not wants_create_event("what is on my calendar tomorrow")


def test_parse_event_time_range():
    text = "set a meeting me and haroon ali at 11:30pm to 11:45pm today"
    now = datetime(2026, 6, 20, 10, 0, tzinfo=ZoneInfo("Asia/Karachi"))
    parsed = parse_event_time_range(text, now=now)
    assert parsed is not None
    start, duration = parsed
    assert start.hour == 23
    assert start.minute == 30
    assert duration == 15


def test_parse_event_title_me_and_guest():
    text = "set a meeting me and haroon ali at 11:30pm to 11:45pm today"
    assert parse_event_title(text) == "Meeting with Haroon Ali"


def test_parse_attendee_emails_me_and_guest():
    text = "set a meeting me and haroon ali at 11:30pm to 11:45pm today"
    with patch("tempa.channels.calendar.events._resolve_name_to_email", return_value="haroon.ali@taleemabad.com"):
        assert parse_attendee_emails(text) == ["haroon.ali@taleemabad.com"]


def test_parse_event_title_strips_email():
    text = "create a meeting on 6:00 pm name Haroon X tempa with haroon.ali@taleemabad at 6:40pm"
    assert parse_event_title(text) == "Haroon X tempa"


def test_parse_attendee_emails():
    text = "send invite to haroon.ali@taleemabad.com for the meeting"
    assert parse_attendee_emails(text) == ["haroon.ali@taleemabad.com"]


def test_parse_attendee_names_with_guest():
    text = "set a meeting at 11:30pm today with Haroon Ali for 15 minutes for tempa testing"
    from tempa.channels.calendar.events import _attendee_names_from_text

    assert _attendee_names_from_text(text) == ["Haroon Ali"]


def test_parse_attendee_emails_from_contact_name():
    text = "send a invite to haroon ali for tempa testing meeting of 15mins at 7:42"
    with patch("tempa.channels.calendar.events._resolve_name_to_email", return_value="haroon.ali@taleemabad.com"):
        assert parse_attendee_emails(text) == ["haroon.ali@taleemabad.com"]


def test_resolve_guest_excludes_calendar_owner():
    from tempa.channels.gmail.recipients import is_excluded_guest_email, resolve_guest_email_by_name

    owner = "haroon.orenda@gmail.com"
    assert is_excluded_guest_email(owner, owner=owner) is True
    assert is_excluded_guest_email("notifications@github.com", owner=owner) is True

    with (
        patch("tempa.channels.contacts.store.search_contacts") as search_contacts,
        patch("tempa.channels.gmail.recipients.lookup_email_by_name_in_gmail") as gmail_lookup,
        patch("tempa.channels.contacts.sync.sync_contacts_blocking"),
    ):
        search_contacts.return_value = [
            {"name": "Haroon Ali", "email": "haroon.orenda@gmail.com"},
            {"name": "Haroon Ali", "email": "haroon.ali@taleemabad.com"},
        ]
        gmail_lookup.return_value = {}
        assert resolve_guest_email_by_name("Haroon Ali", owner=owner) == "haroon.ali@taleemabad.com"


def test_external_attendees_from_event_raw():
    from tempa.channels.calendar.events import external_attendees_from_event_raw

    with patch("tempa.channels.calendar.events.get_calendar_owner_email", return_value="haroon.orenda@gmail.com"):
        raw = {
            "attendees": [
                {"email": "haroon.orenda@gmail.com", "organizer": True, "self": True},
                {"email": "haroon.ali@taleemabad.com", "responseStatus": "needsAction"},
            ]
        }
        assert external_attendees_from_event_raw(raw) == ["haroon.ali@taleemabad.com"]


def test_parse_event_title_for_meeting_pattern():
    text = "send a invite to haroon ali for tempa testing meeting of 15mins at 7:42"
    assert parse_event_title(text) == "tempa testing"


def test_parse_event_duration():
    assert parse_event_duration("meeting of 15mins at 7pm") == 15
    assert parse_event_duration("one hour meeting") == 60


def test_should_auto_join_meet_soon():
    from datetime import timedelta

    from tempa.channels.calendar.events import _local_tz, should_auto_join_meet

    now = datetime.now(_local_tz())
    assert should_auto_join_meet(now + timedelta(minutes=4)) is True
    assert should_auto_join_meet(now + timedelta(hours=3)) is False


def test_parse_event_start_uses_last_time():
    text = "create meeting on 6:00 pm name Test with guest at 6:40pm today"
    now = datetime(2026, 6, 17, 16, 0, tzinfo=ZoneInfo("Asia/Karachi"))
    start = parse_event_start(text, now=now)
    assert start is not None
    assert start.hour == 18
    assert start.minute == 40


def test_parse_event_title_and_time():
    text = "make a meeting on calender around 5:10pm name tempa testing"
    assert parse_event_title(text) == "tempa testing"
    now = datetime(2026, 6, 16, 16, 0, tzinfo=ZoneInfo("Asia/Karachi"))
    start = parse_event_start(text, now=now)
    assert start is not None
    assert start.hour == 17
    assert start.minute == 10


def test_format_calendar_api_disabled_error():
    err = format_calendar_error(
        Exception("accessNotConfigured: Google Calendar API has not been used in project")
    )
    assert "enable" in err.lower()
    assert "Google Calendar API" in err


def test_try_create_event_success():
    mock_event = MagicMock()
    mock_event.id = "evt-1"
    mock_event.meet_url = "https://meet.google.com/abc-defg-hij"
    with (
        patch("tempa.channels.calendar.events.load_calendar_client") as load_client,
        patch("tempa.channels.calendar.events.ingest_calendar_event"),
        patch("tempa.channels.calendar.session_state.record_calendar_event"),
    ):
        client = MagicMock()
        client.create_event.return_value = mock_event
        load_client.return_value = client

        result = try_create_event_from_message(
            "create meeting at 5:10pm name Tempa Testing",
        )
        assert result.ok is True
        assert result.summary == "Tempa Testing"
        assert result.meet_url == "https://meet.google.com/abc-defg-hij"
        client.create_event.assert_called_once()


def test_wants_delete_event():
    assert wants_delete_event("remove tempa testing metting from calender")
    assert wants_delete_event("still i see delete it")
    assert not wants_delete_event("what is on my calendar")


def test_parse_delete_title():
    assert parse_delete_title("remove tempa testing meeting from calendar") == "tempa testing"
    assert (
        parse_delete_title(
            "delete it",
            recent_texts=["make a meeting name tempa testing at 5:10pm"],
        )
        == "tempa testing"
    )


def test_try_invite_guests_success():
    mock_event = MagicMock()
    mock_event.id = "evt-1"
    mock_event.summary = "Haroon X tempa"
    with (
        patch("tempa.channels.calendar.events.load_calendar_client") as load_client,
        patch("tempa.channels.calendar.events.resolve_event_for_invite", return_value=mock_event),
        patch("tempa.channels.calendar.session_state.record_calendar_event"),
        patch("tempa.channels.calendar.session_state.get_last_calendar_event", return_value={}),
    ):
        client = MagicMock()
        updated = MagicMock()
        updated.id = "evt-1"
        updated.summary = "Haroon X tempa"
        client.add_attendees.return_value = updated
        load_client.return_value = client

        result = try_invite_guests_from_message(
            "send invite on calendar to haroon.ali@taleemabad.com",
            recent_texts=["create meeting name Haroon X tempa at 6:40pm"],
        )
        assert result.ok is True
        client.add_attendees.assert_called_once()


def test_try_delete_event_success():
    mock_event = MagicMock()
    mock_event.id = "evt-1"
    mock_event.summary = "Tempa Testing"
    with patch("tempa.channels.calendar.events.load_calendar_client") as load_client:
        client = MagicMock()
        client.list_upcoming_events.return_value = [mock_event]
        load_client.return_value = client

        result = try_delete_event_from_message("remove Tempa Testing meeting from calendar")
        assert result.ok is True
        assert result.deleted == ["Tempa Testing"]
        client.delete_event.assert_called_once_with("evt-1")
