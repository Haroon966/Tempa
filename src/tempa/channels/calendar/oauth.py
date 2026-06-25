from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from tempa.channels.calendar.client import DEFAULT_SCOPES, GoogleCalendar
from tempa.settings import get_settings

REDIRECT_PATH = "/api/connections/google/callback"


def _credentials_path() -> Path:
    return get_settings().sessions_dir / "google" / "credentials.json"


def _sync_credentials_from_env() -> None:
    """Keep credentials.json aligned with GOOGLE_CLIENT_ID/SECRET from .env."""
    settings = get_settings()
    cid = settings.google_client_id.strip()
    secret = settings.google_client_secret.strip()
    if not cid or not secret:
        return
    path = _credentials_path()
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            web = existing.get("web", {})
            if web.get("client_id") == cid and web.get("client_secret") == secret:
                return
        except Exception:
            pass
    save_google_credentials(cid, secret)


def google_credentials_configured() -> bool:
    _sync_credentials_from_env()
    settings = get_settings()
    if settings.google_client_id and settings.google_client_secret:
        return True
    return _credentials_path().exists()


def save_google_credentials(client_id: str, client_secret: str) -> None:
    settings = get_settings()
    cid = client_id.strip()
    secret = client_secret.strip()
    if not cid or not secret:
        raise ValueError("Google client ID and secret are required")
    port = settings.tempa_daemon_port
    redirect_uris = [
        f"http://localhost:{port}/api/connections/google/callback",
        f"http://localhost:{port}/api/connections/gmail/callback",
    ]
    config = {
        "web": {
            "client_id": cid,
            "client_secret": secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": redirect_uris,
        }
    }
    path = _credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config), encoding="utf-8")
    settings.google_client_id = cid
    settings.google_client_secret = secret


def client_secret_path() -> Path:
    _sync_credentials_from_env()
    path = _credentials_path()
    if not path.exists():
        raise FileNotFoundError("Google OAuth credentials not configured")
    return path


def _pending_oauth_path() -> Path:
    return get_settings().sessions_dir / "google" / "oauth_pending.json"


def _save_pending_oauth(state: str, code_verifier: str | None) -> None:
    path = _pending_oauth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"state": state, "code_verifier": code_verifier}),
        encoding="utf-8",
    )


def _load_pending_oauth() -> dict[str, str | None]:
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
    legacy = get_settings().sessions_dir / "google" / "oauth_state.txt"
    if legacy.exists():
        legacy.unlink()


def get_oauth_flow() -> Flow:
    settings = get_settings()
    secret = client_secret_path()
    return Flow.from_client_secrets_file(
        str(secret),
        scopes=list(DEFAULT_SCOPES),
        redirect_uri=f"http://localhost:{settings.tempa_daemon_port}{REDIRECT_PATH}",
    )


def authorization_url() -> str:
    flow = get_oauth_flow()
    # Request only DEFAULT_SCOPES. include_granted_scopes merges prior grants
    # (e.g. calendar.readonly) and oauthlib rejects the expanded scope set.
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    _save_pending_oauth(state, flow.code_verifier)
    return url


def begin_google_connect() -> str:
    """Start a fresh OAuth flow (drops any stale token/scopes)."""
    from tempa.security.sessions import delete_secret_file

    delete_secret_file("google/token.json")
    _clear_pending_oauth()
    return authorization_url()


def handle_oauth_callback(code: str, state: str) -> dict[str, str]:
    settings = get_settings()
    pending = _load_pending_oauth()
    expected = pending.get("state") or ""
    if not expected:
        state_path = settings.sessions_dir / "google" / "oauth_state.txt"
        if state_path.exists():
            expected = state_path.read_text(encoding="utf-8").strip()
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
    from tempa.security.sessions import write_secret_file

    write_secret_file("google/token.json", creds.to_json())
    _clear_pending_oauth()
    return {"status": "connected"}


def load_calendar_client() -> GoogleCalendar | None:
    import json

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    from tempa.security.sessions import read_secret_file, secret_file_exists, write_secret_file

    if not secret_file_exists("google/token.json"):
        return None

    token_json = read_secret_file("google/token.json")
    if not token_json:
        return None

    creds = Credentials.from_authorized_user_info(json.loads(token_json))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        write_secret_file("google/token.json", creds.to_json())
    return GoogleCalendar(creds)


def disconnect_google() -> None:
    from tempa.security.sessions import delete_secret_file

    delete_secret_file("google/token.json")
    _clear_pending_oauth()


__all__ = [
    "authorization_url",
    "begin_google_connect",
    "handle_oauth_callback",
    "load_calendar_client",
    "google_credentials_configured",
    "save_google_credentials",
    "disconnect_google",
    "client_secret_path",
]
