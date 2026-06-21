from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from tempa.channels.calendar.client import DEFAULT_SCOPES
from tempa.channels.calendar.oauth import google_credentials_configured
from tempa.settings import get_settings


def google_connection_status() -> dict:
    import json

    from tempa.security.sessions import read_secret_file, secret_file_exists, write_secret_file

    settings = get_settings()
    creds_ok = google_credentials_configured()
    if not secret_file_exists("google/token.json"):
        return {
            "status": "disconnected",
            "connected": False,
            "credentials_configured": creds_ok,
            "needs_reconnect": False,
        }
    try:
        token_json = read_secret_file("google/token.json")
        if not token_json:
            return {
                "status": "disconnected",
                "connected": False,
                "credentials_configured": creds_ok,
                "needs_reconnect": False,
            }
        # Don't pass `scopes=` here: the stored token already contains the
        # originally-authorized scopes. Passing a different list can raise:
        # "Scope has changed from ... to ...", even though the token is usable.
        creds = Credentials.from_authorized_user_info(json.loads(token_json))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            write_secret_file("google/token.json", creds.to_json())

        scopes = list(creds.scopes or [])
        has_write_scope = any(
            s == "https://www.googleapis.com/auth/calendar"
            or ("/calendar" in s and "readonly" not in s)
            for s in scopes
        )
        needs_reconnect = creds.valid and not has_write_scope

        calendar_ok = False
        calendar_detail = ""
        if creds.valid and not needs_reconnect:
            from tempa.channels.calendar.oauth import load_calendar_client

            client = load_calendar_client()
            if client is not None:
                try:
                    from datetime import datetime, timedelta, timezone

                    now = datetime.now(timezone.utc)
                    client.list_upcoming_events(
                        calendar_id="primary",
                        time_min=now,
                        time_max=now + timedelta(hours=1),
                        max_results=1,
                    )
                    calendar_ok = True
                except Exception as exc:
                    calendar_detail = str(exc)[:240]

        status = "connected" if creds.valid and calendar_ok else "degraded"
        if needs_reconnect:
            status = "needs_reconnect"
        elif creds.valid and not calendar_ok and not needs_reconnect:
            status = "degraded"

        return {
            "status": status,
            "connected": creds.valid and not needs_reconnect,
            "credentials_configured": creds_ok,
            "needs_reconnect": needs_reconnect,
            "calendar_api_ok": calendar_ok,
            "detail": calendar_detail,
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
