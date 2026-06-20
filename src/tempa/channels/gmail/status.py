from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from tempa.channels.calendar.oauth import google_credentials_configured
from tempa.settings import get_settings


def gmail_connection_status() -> dict:
    settings = get_settings()
    creds_ok = google_credentials_configured()
    if not settings.gmail_token_path.exists():
        return {
            "status": "disconnected",
            "connected": False,
            "credentials_configured": creds_ok,
            "needs_reconnect": False,
        }
    try:
        creds = Credentials.from_authorized_user_file(str(settings.gmail_token_path))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            settings.gmail_token_path.write_text(creds.to_json(), encoding="utf-8")

        scopes = list(creds.scopes or [])
        has_gmail_scope = any(
            s in scopes
            for s in (
                "https://mail.google.com/",
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/gmail.readonly",
            )
        )
        needs_reconnect = creds.valid and not has_gmail_scope

        gmail_ok = False
        email_address = ""
        detail = ""
        if creds.valid and not needs_reconnect:
            from tempa.channels.gmail.oauth import load_gmail_client

            client = load_gmail_client()
            if client is not None:
                try:
                    profile = client.get_profile()
                    gmail_ok = True
                    email_address = str(profile.get("emailAddress", ""))
                except Exception as exc:
                    detail = str(exc)[:240]

        status = "connected" if creds.valid and gmail_ok else "degraded"
        if needs_reconnect:
            status = "needs_reconnect"
        elif creds.valid and not gmail_ok and not needs_reconnect:
            status = "degraded"

        return {
            "status": status,
            "connected": creds.valid and gmail_ok and not needs_reconnect,
            "credentials_configured": creds_ok,
            "needs_reconnect": needs_reconnect,
            "gmail_api_ok": gmail_ok,
            "email_address": email_address,
            "detail": detail,
            "scopes": scopes,
        }
    except Exception as exc:
        return {
            "status": "error",
            "connected": False,
            "credentials_configured": creds_ok,
            "needs_reconnect": True,
            "detail": str(exc),
        }
