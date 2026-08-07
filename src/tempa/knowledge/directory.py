"""Build a durable people/channels knowledge directory for the agent vault."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_NOISE_EMAIL = re.compile(
    r"(noreply|no-reply|mailer-daemon|notifications?@|.*@noreply\.|.*\.github\.com$)",
    re.I,
)


def knowledge_dir() -> Path:
    path = get_settings().varys_vault_dir / "knowledge"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_useful_email(email: str) -> bool:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False
    if _NOISE_EMAIL.search(email):
        return False
    return True


def _load_identity_links() -> dict[str, Any]:
    path = get_settings().sessions_dir / "contacts" / "identity_links.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_whatsapp_peers() -> list[dict[str, Any]]:
    path = get_settings().sessions_dir / "whatsapp" / "peers.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, dict):
        rows = []
        for key, val in data.items():
            if isinstance(val, dict):
                rows.append({"id": key, **val})
            else:
                rows.append({"id": key, "name": str(val)})
        return rows
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def _load_contacts_rows(*, limit: int = 400) -> list[dict[str, Any]]:
    import sqlite3

    db = get_settings().db_path
    if not db.exists():
        return []
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, name, email, phone, source FROM contacts "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _fetch_slack_directory() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from tempa.channels.slack.client import list_conversations, list_users, load_slack_client
    from tempa.channels.slack.session import slack_configured

    if not slack_configured():
        return [], []
    client = load_slack_client()
    channels: list[dict[str, Any]] = []
    for ch in list_conversations(client, types="public_channel,private_channel", limit=200):
        if ch.get("is_archived"):
            continue
        channels.append(
            {
                "id": ch.get("id"),
                "name": ch.get("name"),
                "is_private": bool(ch.get("is_private")),
                "is_member": bool(ch.get("is_member")),
                "topic": ((ch.get("topic") or {}).get("value") or "")[:120],
            }
        )
    channels.sort(key=lambda c: (not c.get("is_member"), str(c.get("name") or "").lower()))

    people: list[dict[str, Any]] = []
    for user in list_users(client):
        if user.get("deleted") or user.get("is_bot") or user.get("id") == "USLACKBOT":
            continue
        profile = user.get("profile") or {}
        email = str(profile.get("email") or "").strip()
        name = (
            str(profile.get("real_name") or profile.get("display_name") or user.get("name") or "")
            .strip()
        )
        if not name:
            continue
        people.append(
            {
                "name": name,
                "slack_id": user.get("id"),
                "slack_handle": user.get("name"),
                "email": email,
                "title": str(profile.get("title") or "").strip(),
            }
        )
    people.sort(key=lambda p: str(p.get("name") or "").lower())
    return channels, people


def _render_channels(channels: list[dict[str, Any]]) -> str:
    lines = [
        "# Slack channels",
        "",
        "Use these ids/names when sending Slack messages. Prefer channels where `member: yes`.",
        "",
        "| Channel | ID | Member | Private | Notes |",
        "|---------|----|--------|---------|-------|",
    ]
    for ch in channels:
        name = ch.get("name") or ""
        lines.append(
            f"| #{name} | `{ch.get('id')}` | "
            f"{'yes' if ch.get('is_member') else 'no'} | "
            f"{'yes' if ch.get('is_private') else 'no'} | "
            f"{(ch.get('topic') or '').replace('|', '/')} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_people(
    slack_people: list[dict[str, Any]],
    contacts: list[dict[str, Any]],
    identity: dict[str, Any],
    wa_peers: list[dict[str, Any]],
) -> str:
    by_email: dict[str, dict[str, Any]] = {}

    def row_for(email: str) -> dict[str, Any]:
        email = email.lower()
        if email not in by_email:
            by_email[email] = {
                "name": "",
                "email": email,
                "slack_id": "",
                "slack_handle": "",
                "phone": "",
                "whatsapp": "",
                "title": "",
                "aliases": "",
            }
        return by_email[email]

    def better_name(current: str, candidate: str) -> str:
        cur = (current or "").strip()
        cand = (candidate or "").strip()
        if not cand:
            return cur
        if not cur:
            return cand
        # Prefer fuller real names over single-letter Gmail scraps.
        if len(cand) > len(cur) + 1:
            return cand
        return cur

    for p in slack_people:
        email = str(p.get("email") or "").strip().lower()
        if email and _is_useful_email(email):
            r = row_for(email)
            r["name"] = better_name(r["name"], str(p.get("name") or ""))
            r["slack_id"] = p.get("slack_id") or r["slack_id"]
            r["slack_handle"] = p.get("slack_handle") or r["slack_handle"]
            r["title"] = p.get("title") or r["title"]
        elif p.get("slack_id"):
            # No email — key by slack id under synthetic email slot
            key = f"slack:{p['slack_id']}"
            by_email[key] = {
                "name": p.get("name") or "",
                "email": "",
                "slack_id": p.get("slack_id") or "",
                "slack_handle": p.get("slack_handle") or "",
                "phone": "",
                "whatsapp": "",
                "title": p.get("title") or "",
                "aliases": "",
            }

    for c in contacts:
        email = str(c.get("email") or "").strip().lower()
        if not _is_useful_email(email):
            continue
        r = row_for(email)
        r["name"] = better_name(r["name"], str(c.get("name") or ""))
        phone = str(c.get("phone") or "").strip()
        if phone and not r["phone"]:
            r["phone"] = phone

    for email, link in identity.items():
        if not isinstance(link, dict):
            continue
        email_l = str(email).strip().lower()
        if not _is_useful_email(email_l):
            continue
        r = row_for(email_l)
        slack_id = str(link.get("slack_user_id") or link.get("slack_id") or "").strip()
        if slack_id and not r["slack_id"]:
            r["slack_id"] = slack_id
        name = str(link.get("name") or link.get("display_name") or "").strip()
        r["name"] = better_name(r["name"], name)

    for peer in wa_peers:
        name = str(peer.get("name") or peer.get("push_name") or "").strip()
        phone = str(peer.get("phone") or peer.get("number") or peer.get("id") or "").strip()
        if not name and not phone:
            continue
        # Match by name to an existing row when possible
        matched = None
        for r in by_email.values():
            if name and r["name"] and name.lower() == r["name"].lower():
                matched = r
                break
        if matched:
            matched["whatsapp"] = phone
            if phone and not matched["phone"]:
                matched["phone"] = phone
        else:
            by_email[f"wa:{phone or name}"] = {
                "name": name,
                "email": "",
                "slack_id": "",
                "slack_handle": "",
                "phone": phone,
                "whatsapp": phone,
                "title": "",
                "aliases": "whatsapp peer",
            }

    rows = sorted(by_email.values(), key=lambda r: (r.get("name") or r.get("email") or "").lower())
    lines = [
        "# People directory",
        "",
        "Use these fields to message people without re-looking-up IDs.",
        "- Slack: prefer `slack_id` (DM) or `@handle`",
        "- Email: use `email`",
        "- WhatsApp: use `whatsapp` / `phone` (E.164 when available)",
        "",
        "| Name | Email | Slack ID | Handle | Phone / WhatsApp | Title |",
        "|------|-------|----------|--------|------------------|-------|",
    ]
    for r in rows:
        if not (r.get("name") or r.get("email") or r.get("slack_id")):
            continue
        phone = r.get("whatsapp") or r.get("phone") or ""
        lines.append(
            f"| {r.get('name') or '—'} | {r.get('email') or '—'} | "
            f"`{r.get('slack_id') or '—'}` | {r.get('slack_handle') or '—'} | "
            f"{phone or '—'} | {(r.get('title') or '').replace('|', '/')} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_routing() -> str:
    settings = get_settings()
    moawin = getattr(settings, "meet_moawin_huddle_slack_channel", "") or "region-punjab-moawin"
    punjab = getattr(settings, "meet_punjab_daily_sync_slack_channel", "") or "region-punjab"
    owner = getattr(settings, "slack_owner_user_id", "") or ""
    return "\n".join(
        [
            "# Routing aliases",
            "",
            "Short names the agent should resolve without searching.",
            "",
            "| Alias | Means | Channel / target |",
            "|-------|-------|------------------|",
            f"| Moawin huddle / Daily Huddle-Moawin | post-meeting summary channel | `#{moawin}` |",
            f"| Punjab daily sync / Team Punjab | meeting summary channel | `#{punjab}` |",
            f"| owner / Sameer | Slack DM owner | `{owner or 'SLACK_OWNER_USER_ID'}` |",
            "",
            "When asked to message a person or channel:",
            "1. Check `knowledge/people.md` and `knowledge/channels.md` first.",
            "2. Only call live Slack/contacts APIs if the directory miss.",
            "3. Prefer Slack channel id / user id over fuzzy name search when listed.",
            "",
        ]
    )


def refresh_knowledge_directory() -> dict[str, Any]:
    """Write knowledge/*.md from live Slack + contacts + WhatsApp peers."""
    root = knowledge_dir()
    channels, slack_people = _fetch_slack_directory()
    contacts = _load_contacts_rows()
    identity = _load_identity_links()
    wa_peers = _load_whatsapp_peers()

    channels_md = _render_channels(channels) if channels else (
        "# Slack channels\n\n_No channels loaded (Slack not configured or empty)._\n"
    )
    people_md = _render_people(slack_people, contacts, identity, wa_peers)
    routing_md = _render_routing()
    index_md = "\n".join(
        [
            "# Knowledge directory",
            "",
            f"Last refreshed: {datetime.now(timezone.utc).isoformat()}",
            "",
            "Agent address book for messaging. Files:",
            "- `channels.md` — Slack channels (id + membership)",
            "- `people.md` — people with Slack / email / WhatsApp",
            "- `routing.md` — short aliases (Moawin huddle, Punjab, owner)",
            "",
            "Do not re-fetch directory data every turn — use these files first.",
            "",
        ]
    )

    (root / "README.md").write_text(index_md, encoding="utf-8")
    (root / "channels.md").write_text(channels_md, encoding="utf-8")
    (root / "people.md").write_text(people_md, encoding="utf-8")
    (root / "routing.md").write_text(routing_md, encoding="utf-8")

    # Machine-readable dump for tooling / future lookups.
    raw = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "channels": channels,
        "slack_people": slack_people,
        "whatsapp_peers": wa_peers,
    }
    (root / "directory.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

    result = {
        "path": str(root),
        "channels": len(channels),
        "slack_people": len(slack_people),
        "contacts_scanned": len(contacts),
        "whatsapp_peers": len(wa_peers),
    }
    logger.info("Knowledge directory refreshed: %s", result)
    return result
