from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from tempa.settings import get_settings

_EMAIL_RE = re.compile(r"^[\w.\-+]+@[\w.\-]+\.\w+$", re.I)


def _links_path():
    path = get_settings().sessions_dir / "contacts" / "identity_links.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _load_links() -> dict[str, dict[str, Any]]:
    path = _links_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_links(links: dict[str, dict[str, Any]]) -> None:
    _links_path().write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")


def _list_all_contacts() -> list[dict[str, Any]]:
    settings = get_settings()
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT id, name, email, phone, source, updated_at FROM contacts ORDER BY name"
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def _merge_entry(links: dict[str, dict[str, Any]], email: str, contact: dict[str, Any]) -> None:
    cid = str(contact.get("id") or "")
    if not cid:
        return
    entry = links.setdefault(
        email,
        {
            "slack_ids": [],
            "jira_account_ids": [],
            "gmail_ids": [],
            "display_name": "",
        },
    )
    name = str(contact.get("name") or "").strip()
    if name and not entry.get("display_name"):
        entry["display_name"] = name
    elif name and len(name) > len(str(entry.get("display_name") or "")):
        entry["display_name"] = name

    if cid.startswith("slack:"):
        slack_id = cid.split(":", 1)[1]
        if slack_id and slack_id not in entry["slack_ids"]:
            entry["slack_ids"].append(slack_id)
    elif cid.startswith("jira:"):
        account_id = cid.split(":", 1)[1]
        if account_id and account_id not in entry["jira_account_ids"]:
            entry["jira_account_ids"].append(account_id)
    elif cid.startswith("gmail:") or contact.get("source") == "gmail":
        if cid not in entry["gmail_ids"]:
            entry["gmail_ids"].append(cid)
    elif "@" in cid:
        if cid not in entry["gmail_ids"]:
            entry["gmail_ids"].append(cid)


def link_identities() -> dict[str, Any]:
    contacts = _list_all_contacts()
    links: dict[str, dict[str, Any]] = {}
    for contact in contacts:
        email = normalize_email(str(contact.get("email") or ""))
        if not email or not _EMAIL_RE.match(email):
            continue
        _merge_entry(links, email, contact)
    _save_links(links)
    return {"status": "ok", "identity_link_count": len(links)}


def identity_link_count() -> int:
    return len(_load_links())


def lookup_identity(query_or_email: str) -> dict[str, Any] | None:
    query = (query_or_email or "").strip()
    if not query:
        return None
    links = _load_links()
    email = normalize_email(query)
    if email in links:
        return dict(links[email])
    lower = query.lower()
    for key, entry in links.items():
        if lower in key or lower in str(entry.get("display_name") or "").lower():
            return dict(entry)
    return None


def resolve_slack_to_jira(slack_user_id: str) -> dict[str, Any] | None:
    if not slack_user_id:
        return None
    links = _load_links()
    for entry in links.values():
        if slack_user_id in (entry.get("slack_ids") or []):
            account_ids = entry.get("jira_account_ids") or []
            if account_ids:
                return {
                    "account_id": account_ids[0],
                    "display_name": entry.get("display_name") or "",
                    "email": "",
                    "source": "link",
                }
    contact_id = f"slack:{slack_user_id}"
    for contact in _list_all_contacts():
        if contact.get("id") != contact_id:
            continue
        email = normalize_email(str(contact.get("email") or ""))
        if email and email in links:
            account_ids = links[email].get("jira_account_ids") or []
            if account_ids:
                return {
                    "account_id": account_ids[0],
                    "display_name": links[email].get("display_name") or contact.get("name") or "",
                    "email": email,
                    "source": "link",
                }
    return None


def resolve_name_to_jira(name: str) -> list[dict[str, Any]]:
    name = (name or "").strip()
    if not name:
        return []
    links = _load_links()
    lower = name.lower()
    matches: list[dict[str, Any]] = []
    for email, entry in links.items():
        display = str(entry.get("display_name") or "").lower()
        if lower in display or display.startswith(lower) or any(w in display for w in lower.split()):
            account_ids = entry.get("jira_account_ids") or []
            if account_ids:
                matches.append(
                    {
                        "account_id": account_ids[0],
                        "display_name": entry.get("display_name") or email,
                        "email": email,
                        "source": "link",
                    }
                )
    return matches
