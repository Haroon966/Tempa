from __future__ import annotations

from tempa.agents.grounding import build_grounding_pack
from tempa.router.verifier import verify_reply


def test_verifier_catches_false_unread_claim():
    pack = build_grounding_pack(
        "how many unread emails?",
        {"channel": "dashboard"},
    )
    pack["gmail_compact"] = "Gmail: connected\nInbox: 3 unread"
    ok, corrected = verify_reply("You have no unread emails.", pack)
    assert not ok
    assert "3" in corrected


def test_grounding_pack_has_sync_fields():
    pack = build_grounding_pack("hello", {"channel": "dashboard"})
    assert "gmail_last_sync_at" in pack
    assert "calendar_last_sync_at" in pack


def test_sync_status_record():
    from tempa.core.sync_status import get_sync_status, record_sync

    record_sync("gmail", status="error", error="test failure")
    row = get_sync_status("gmail")
    assert row.get("sync_status") == "error"
    assert "test failure" in str(row.get("last_sync_error", ""))


def test_whatsapp_dedupe_persisted():
    from tempa.channels.whatsapp.dedupe import bootstrap, is_seen, mark_seen

    bootstrap()
    assert mark_seen("msg-123") is True
    assert mark_seen("msg-123") is False
    assert is_seen("msg-123") is True
