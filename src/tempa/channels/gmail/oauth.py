from __future__ import annotations

import os

from tempa.channels.calendar.oauth import (
    REDIRECT_PATH,
    client_secret_path,
    google_credentials_configured,
    save_google_credentials,
)
from tempa.channels.gmail.client import DEFAULT_SCOPES, GmailClient
from tempa.settings import get_settings

# Reuse Calendar's registered redirect URI to avoid redirect_uri_mismatch in Google Cloud.


def _pending_oauth_path():
    return get_settings().sessions_dir / "gmail" / "oauth_pending.json"


def _save_pending_oauth(state: str, code_verifier: str | None) -> None:
    import json

    path = _pending_oauth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"state": state, "code_verifier": code_verifier}),
        encoding="utf-8",
    )


def _load_pending_oauth() -> dict[str, str | None]:
    import json

    path = _pending_oauth_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "state": str(data.get("state") or ""),
            "code_verifier": data.get("code_verifier"),
        }
    except Exception:
        return {}


def _clear_pending_oauth() -> None:
    path = _pending_oauth_path()
    if path.exists():
        path.unlink()


def get_oauth_flow():
    from google_auth_oauthlib.flow import Flow

    settings = get_settings()
    return Flow.from_client_secrets_file(
        str(client_secret_path()),
        scopes=list(DEFAULT_SCOPES),
        redirect_uri=f"http://localhost:{settings.tempa_daemon_port}{REDIRECT_PATH}",
    )


def authorization_url() -> str:
    flow = get_oauth_flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    _save_pending_oauth(state, flow.code_verifier)
    return url


def begin_gmail_connect() -> str:
    settings = get_settings()
    if settings.gmail_token_path.exists():
        settings.gmail_token_path.unlink()
    _clear_pending_oauth()
    return authorization_url()


def handle_oauth_callback(code: str, state: str) -> dict[str, str]:
    settings = get_settings()
    pending = _load_pending_oauth()
    expected = pending.get("state") or ""
    if expected and state != expected:
        raise ValueError("Invalid OAuth state")
    flow = get_oauth_flow()
    verifier = pending.get("code_verifier")
    if verifier:
        flow.code_verifier = verifier
    prev_relax = os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE")
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
    try:
        flow.fetch_token(code=code)
    finally:
        if prev_relax is None:
            os.environ.pop("OAUTHLIB_RELAX_TOKEN_SCOPE", None)
        else:
            os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = prev_relax
    creds = flow.credentials
    settings.gmail_token_path.parent.mkdir(parents=True, exist_ok=True)
    settings.gmail_token_path.write_text(creds.to_json(), encoding="utf-8")
    _clear_pending_oauth()
    return {"status": "connected"}


def load_gmail_client() -> GmailClient | None:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    settings = get_settings()
    if not settings.gmail_token_path.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(settings.gmail_token_path))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        settings.gmail_token_path.write_text(creds.to_json(), encoding="utf-8")
    return GmailClient(creds)


def disconnect_gmail() -> None:
    settings = get_settings()
    if settings.gmail_token_path.exists():
        settings.gmail_token_path.unlink()
    _clear_pending_oauth()


def gmail_oauth_pending_state() -> str:
    return str(_load_pending_oauth().get("state") or "")


def is_gmail_oauth_state(state: str) -> bool:
    expected = gmail_oauth_pending_state()
    return bool(expected and state == expected)


__all__ = [
    "REDIRECT_PATH",
    "authorization_url",
    "begin_gmail_connect",
    "disconnect_gmail",
    "google_credentials_configured",
    "gmail_oauth_pending_state",
    "handle_oauth_callback",
    "is_gmail_oauth_state",
    "load_gmail_client",
    "save_google_credentials",
]
