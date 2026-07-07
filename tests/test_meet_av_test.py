import pytest

from tempa.meet.service import _clamp_duration_seconds, _resolve_av_test_youtube_url
from tempa.settings import Settings


def test_clamp_duration_seconds():
    assert _clamp_duration_seconds(30) == 60
    assert _clamp_duration_seconds(3600) == 3600
    assert _clamp_duration_seconds(999999) == 28800


def test_resolve_av_test_disabled(monkeypatch):
    monkeypatch.setattr(
        "tempa.meet.service.get_settings",
        lambda: Settings(meet_av_test_enabled=False),
    )
    with pytest.raises(RuntimeError, match="disabled"):
        _resolve_av_test_youtube_url("https://www.youtube.com/watch?v=abc")


def test_resolve_av_test_requires_youtube(monkeypatch):
    monkeypatch.setattr(
        "tempa.meet.service.get_settings",
        lambda: Settings(meet_av_test_enabled=True),
    )
    with pytest.raises(RuntimeError, match="YouTube"):
        _resolve_av_test_youtube_url("https://example.com/video")


def test_resolve_av_test_ok(monkeypatch):
    monkeypatch.setattr(
        "tempa.meet.service.get_settings",
        lambda: Settings(meet_av_test_enabled=True),
    )
    url = "https://www.youtube.com/watch?v=abc"
    assert _resolve_av_test_youtube_url(url) == url
    assert _resolve_av_test_youtube_url(None) is None
