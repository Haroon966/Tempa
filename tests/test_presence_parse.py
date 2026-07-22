"""Tests for #presence keyword classifier (full taxonomy)."""

from __future__ import annotations

from datetime import date

from tempa.channels.slack.presence_parse import classify_presence_text, dates_for_classification


def test_leave_and_sick():
    r = classify_presence_text("On leave today due to sore throat and fever.", base_date=date(2026, 7, 20))
    assert r["status"] == "leave"
    assert r["reason"] == "sick"
    assert r["when_start"] == "2026-07-20"


def test_remote_and_i10_office():
    remote = classify_presence_text("Working remotely today", base_date=date(2026, 7, 20))
    assert remote["status"] == "remote"
    i10 = classify_presence_text("Working from I10 today!", base_date=date(2026, 7, 20))
    assert i10["status"] == "office"
    assert i10["location"] == "i10"


def test_niete_h9_rawalpindi_moawin():
    n = classify_presence_text("Will join in 2nd half at Niete", base_date=date(2026, 7, 20))
    assert n["location"] == "niete"
    h = classify_presence_text("Working from h9 today", base_date=date(2026, 7, 20))
    assert h["location"] == "h9"
    r = classify_presence_text("At Rawalpindi office", base_date=date(2026, 7, 20))
    assert r["location"] == "rawalpindi"
    m = classify_presence_text("On Moawin HO visit", base_date=date(2026, 7, 20))
    assert m["status"] == "field_visit"
    assert m["location"] == "moawin_hq"


def test_school_visit_not_leave():
    r = classify_presence_text("On school visits today", base_date=date(2026, 7, 20))
    assert r["status"] == "field_visit"


def test_half_day_leave_early_partial():
    assert classify_presence_text("Need to leave early/half day", base_date=date(2026, 7, 20))["status"] in {
        "half_day",
        "leave_early",
    }
    assert classify_presence_text("Signing off early", base_date=date(2026, 7, 20))["status"] == "leave_early"
    p = classify_presence_text("Away in 1st half.", base_date=date(2026, 7, 20))
    assert p["status"] == "partial_away"
    assert p["half"] == "first"


def test_late_ooo_limited_travel_back():
    assert classify_presence_text("Running a bit late", base_date=date(2026, 7, 20))["status"] == "late"
    assert classify_presence_text("OOO for 30 mins", base_date=date(2026, 7, 20))["status"] == "ooo"
    assert classify_presence_text("Limited availability due to internet instability", base_date=date(2026, 7, 20))[
        "status"
    ] == "limited"
    assert classify_presence_text("I'm en route to Sahiwal.", base_date=date(2026, 7, 20))["status"] == "travel"
    assert classify_presence_text("back to office", base_date=date(2026, 7, 20))["status"] == "back"


def test_tomorrow_expands():
    r = classify_presence_text("On leave tomorrow", base_date=date(2026, 7, 20))
    assert r["when"] == "tomorrow"
    assert r["when_start"] == "2026-07-21"
    days = dates_for_classification(r)
    assert days == ["2026-07-21"]


def test_strips_mentions():
    r = classify_presence_text(
        "Working remotely <#C0AV0MUTCJW> <@U0AT5THR0K1>",
        base_date=date(2026, 7, 20),
    )
    assert r["status"] == "remote"
    assert "<@" not in r["raw_text"]


def test_silent_members_implied_office(tmp_path, monkeypatch):
    """Channel members with no post for the day appear as office/implied."""
    from tempa.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(type(settings), "sessions_dir", property(lambda self: tmp_path))

    from tempa.channels.slack import presence_store as ps

    ps.save_members([{"user_id": "U1", "name": "Poster"}, {"user_id": "U2", "name": "Silent"}])
    ps.upsert_presence(
        day="2026-07-20",
        user_id="U1",
        display_name="Poster",
        classification={"status": "leave", "source": "rules", "note": "On leave"},
        message_ts="123.456",
    )
    payload = ps.build_payload("2026-07-20")
    assert [e["user_id"] for e in payload["groups"]["leave"]] == ["U1"]
    office = payload["groups"]["office"]
    assert len(office) == 1
    assert office[0]["user_id"] == "U2"
    assert office[0]["source"] == "implied"
    assert payload["counts"]["office"] == 1


def test_office_location_from_email():
    from tempa.channels.slack.presence_store import _implied_office_entry, office_location_for_email

    assert office_location_for_email("ali@niete.org") == "niete"
    assert office_location_for_email("sara@taleemabad.com") is None
    assert office_location_for_email("") is None
    entry = _implied_office_entry({"user_id": "U1", "name": "Ali", "email": "ali@niete.org"}, "2026-07-20")
    assert entry["location"] == "niete"
