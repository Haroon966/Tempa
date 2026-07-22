"""Public base URL + OAuth redirect for Cloudflare Tunnel / custom domain."""

from __future__ import annotations

from tempa.settings import Settings


def test_resolve_public_base_url_prefers_public() -> None:
    s = Settings(
        tempa_public_base_url="https://tempa.codenest.fun/",
        tempa_daemon_port=8787,
    )
    assert s.resolve_public_base_url() == "https://tempa.codenest.fun"


def test_resolve_public_base_url_falls_back_localhost() -> None:
    s = Settings(tempa_public_base_url="", tempa_daemon_port=8787)
    assert s.resolve_public_base_url() == "http://localhost:8787"


def test_oauth_redirect_uses_public_base(monkeypatch) -> None:
    from tempa.channels.calendar import oauth as oauth_mod

    monkeypatch.setattr(
        oauth_mod,
        "get_settings",
        lambda: Settings(
            tempa_public_base_url="https://tempa.codenest.fun",
            tempa_daemon_port=8787,
        ),
    )
    assert (
        oauth_mod.oauth_redirect_uri()
        == "https://tempa.codenest.fun/api/connections/google/callback"
    )
