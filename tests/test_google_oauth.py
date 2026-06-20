from unittest.mock import MagicMock, patch

from tempa.channels.calendar.oauth import (
    _clear_pending_oauth,
    _load_pending_oauth,
    authorization_url,
    begin_google_connect,
    handle_oauth_callback,
)


def test_authorization_url_persists_pkce_verifier(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    save_google_credentials = __import__(
        "tempa.channels.calendar.oauth", fromlist=["save_google_credentials"]
    ).save_google_credentials
    save_google_credentials("test-client.apps.googleusercontent.com", "test-secret")

    mock_flow = MagicMock()
    mock_flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?x=1", "state-abc")
    mock_flow.code_verifier = "pkce-verifier-123"

    with patch("tempa.channels.calendar.oauth.get_oauth_flow", return_value=mock_flow):
        url = authorization_url()

    assert url.startswith("https://accounts.google.com/")
    pending = _load_pending_oauth()
    assert pending["state"] == "state-abc"
    assert pending["code_verifier"] == "pkce-verifier-123"

    get_settings.cache_clear()


def test_oauth_callback_restores_pkce_verifier(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    oauth = __import__("tempa.channels.calendar.oauth", fromlist=["save_google_credentials", "_save_pending_oauth"])
    oauth.save_google_credentials("test-client.apps.googleusercontent.com", "test-secret")
    oauth._save_pending_oauth("state-abc", "pkce-verifier-123")

    mock_flow = MagicMock()
    mock_creds = MagicMock()
    mock_creds.to_json.return_value = '{"token": "x"}'
    mock_flow.credentials = mock_creds

    with patch("tempa.channels.calendar.oauth.get_oauth_flow", return_value=mock_flow):
        result = handle_oauth_callback("auth-code", "state-abc")

    assert result == {"status": "connected"}
    assert mock_flow.code_verifier == "pkce-verifier-123"
    mock_flow.fetch_token.assert_called_once_with(code="auth-code")
    assert _load_pending_oauth() == {}

    get_settings.cache_clear()
    _clear_pending_oauth()


def test_begin_google_connect_clears_stale_token(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPA_DATA_DIR", str(tmp_path))
    from tempa.settings import get_settings

    get_settings.cache_clear()
    oauth = __import__("tempa.channels.calendar.oauth", fromlist=["save_google_credentials"])
    oauth.save_google_credentials("test-client.apps.googleusercontent.com", "test-secret")
    settings = get_settings()
    settings.google_token_path.parent.mkdir(parents=True, exist_ok=True)
    settings.google_token_path.write_text('{"token": "old"}', encoding="utf-8")

    mock_flow = MagicMock()
    mock_flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?x=1", "state-new")
    mock_flow.code_verifier = "pkce-verifier"

    with patch("tempa.channels.calendar.oauth.get_oauth_flow", return_value=mock_flow):
        url = begin_google_connect()

    assert url.startswith("https://accounts.google.com/")
    assert not settings.google_token_path.exists()

    get_settings.cache_clear()
