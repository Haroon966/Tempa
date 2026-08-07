"""Knowledge directory self-check."""

from __future__ import annotations

from tempa.knowledge.directory import _is_useful_email, _render_routing


def test_noise_emails_filtered():
    assert not _is_useful_email("noreply@github.com")
    assert not _is_useful_email("mailer-daemon@googlemail.com")
    assert _is_useful_email("sameer.sheikh@taleemabad.com")


def test_routing_mentions_moawin(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    text = _render_routing()
    assert "Moawin" in text
    assert "knowledge/people.md" in text
