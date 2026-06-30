from __future__ import annotations

import asyncio
import logging
from typing import Any

from tempa.settings import get_settings

logger = logging.getLogger(__name__)

CONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"


def _has_contacts_scope(creds) -> bool:
    scopes = set(creds.scopes or [])
    return CONTACTS_SCOPE in scopes or any("contacts" in s for s in scopes)


def _load_google_creds(*, require_contacts: bool = False):
    import json

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    from tempa.security.sessions import read_secret_file, secret_file_exists, write_secret_file

    paths = ("gmail/token.json", "google/token.json")
    seen: set[str] = set()
    fallback = None
    for rel in paths:
        if rel in seen or not secret_file_exists(rel):
            continue
        seen.add(rel)
        token_json = read_secret_file(rel)
        if not token_json:
            continue
        creds = Credentials.from_authorized_user_info(json.loads(token_json))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            write_secret_file(rel, creds.to_json())
        if require_contacts and not _has_contacts_scope(creds):
            fallback = fallback or creds
            continue
        return creds
    return fallback


def _people_service():
    from googleapiclient.discovery import build

    creds = _load_google_creds(require_contacts=True)
    if creds is None or not _has_contacts_scope(creds):
        return None
    return build("people", "v1", credentials=creds, cache_discovery=False)


def sync_contacts_blocking() -> dict[str, Any]:
    """Sync contacts from a sync context (WhatsApp/calendar handlers)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(sync_contacts())

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, sync_contacts())
        try:
            return future.result(timeout=45)
        except Exception as exc:
            logger.warning("Contact sync (blocking) failed: %s", exc)
            return {"status": "error", "reason": str(exc)}


def _fetch_google_contacts() -> tuple[list[dict[str, Any]], str | None]:
    service = _people_service()
    if service is None:
        return [], "no_contacts_scope"

    contacts: list[dict[str, Any]] = []
    page_token = None
    try:
        while True:
            result = (
                service.people()
                .connections()
                .list(
                    resourceName="people/me",
                    pageSize=100,
                    personFields="names,emailAddresses,phoneNumbers",
                    pageToken=page_token,
                )
                .execute()
            )
            for person in result.get("connections") or []:
                name = ""
                names = person.get("names") or []
                if names:
                    name = names[0].get("displayName") or names[0].get("givenName") or ""
                emails = [e.get("value", "") for e in (person.get("emailAddresses") or []) if e.get("value")]
                phones = [p.get("value", "") for p in (person.get("phoneNumbers") or []) if p.get("value")]
                if not name and not emails and not phones:
                    continue
                contacts.append(
                    {
                        "id": person.get("resourceName", ""),
                        "name": name,
                        "email": emails[0] if emails else "",
                        "emails": emails,
                        "phone": phones[0] if phones else "",
                        "phones": phones,
                        "source": "google",
                    }
                )
            page_token = result.get("nextPageToken")
            if not page_token:
                break
    except Exception as exc:
        err = str(exc)
        if "insufficient authentication scopes" in err.lower() or "403" in err:
            return [], "no_contacts_scope"
        return [], err
    return contacts, None


async def sync_contacts() -> dict[str, Any]:
    from tempa.channels.contacts.gmail_extract import extract_contacts_from_gmail
    from tempa.channels.contacts.store import upsert_contacts

    results: dict[str, Any] = {}

    try:
        from tempa.channels.slack.sync import sync_slack_contacts

        results["slack"] = await sync_slack_contacts()
    except Exception as exc:
        logger.warning("Slack contact sync failed: %s", exc)
        results["slack"] = {"status": "error", "reason": str(exc)}

    creds = _load_google_creds()
    if creds is None:
        if results.get("slack", {}).get("status") == "ok":
            from tempa.channels.contacts.linker import link_identities

            link_result = link_identities()
            return {
                "status": "ok",
                **results,
                "count": results["slack"].get("count", 0),
                "identity_link_count": link_result.get("identity_link_count", 0),
            }
        return {"status": "skipped", "reason": "Google not connected", **results}

    if not _has_contacts_scope(creds):
        logger.info("Google token lacks contacts scope; using Gmail contact extract")
        gmail_result = await extract_contacts_from_gmail()
        return {"status": gmail_result.get("status", "ok"), **results, **gmail_result}

    contacts, err = await asyncio.to_thread(_fetch_google_contacts)
    if err == "no_contacts_scope":
        logger.info("People API unavailable; falling back to Gmail contact extract")
        gmail_result = await extract_contacts_from_gmail()
        return {"status": gmail_result.get("status", "ok"), **results, **gmail_result}
    if err:
        logger.warning("Contact sync failed: %s", err)
        return {"status": "error", "reason": err, **results}

    count = await upsert_contacts(contacts)
    from tempa.channels.contacts.linker import link_identities

    link_result = link_identities()
    return {"status": "ok", "count": count, "google": count, "identity_link_count": link_result.get("identity_link_count", 0), **results}


def resolve_recipient(query: str) -> dict[str, str]:
    from tempa.channels.contacts.store import search_contacts

    results = search_contacts(query, limit=5)
    for hit in results:
        if hit.get("email"):
            return {
                "email": hit.get("email", ""),
                "phone": hit.get("phone", ""),
                "name": hit.get("name", ""),
            }
    if not results:
        return {"email": query if "@" in query else "", "phone": query if query.isdigit() else "", "name": query}
    hit = results[0]
    return {
        "email": hit.get("email", ""),
        "phone": hit.get("phone", ""),
        "name": hit.get("name", ""),
    }
