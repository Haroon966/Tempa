from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from tempa.channels.contacts.linker import normalize_email, resolve_name_to_jira, resolve_slack_to_jira
from tempa.channels.contacts.store import search_contacts
from tempa.channels.jira.client import get_user_by_account_id, search_users
from tempa.channels.jira.profiles import get_profile

_EMAIL_RE = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")


@dataclass
class ResolveResult:
    account_id: str = ""
    display_name: str = ""
    email: str = ""
    ambiguous: list[dict[str, Any]] = field(default_factory=list)
    missing: bool = False
    needs_input: str = ""
    source: str = ""


def _from_dict(data: dict[str, Any], *, source: str) -> ResolveResult:
    return ResolveResult(
        account_id=str(data.get("account_id") or ""),
        display_name=str(data.get("display_name") or ""),
        email=str(data.get("email") or ""),
        source=source,
    )


def _slack_profile_email(slack_user_id: str) -> str:
    if not slack_user_id:
        return ""
    try:
        from tempa.channels.slack.client import load_slack_client, list_users

        client = load_slack_client()
        if client is None:
            return ""
        for user in list_users(client, limit=5000):
            if str(user.get("id") or "") == slack_user_id:
                profile = user.get("profile") or {}
                return str(profile.get("email") or "")
    except Exception:
        pass
    return ""


def resolve_jira_user(
    name_or_email: str,
    *,
    slack_user_id: str = "",
    session_id: str = "",
    self_assign: bool = False,
) -> ResolveResult:
    if self_assign and slack_user_id:
        name_or_email = slack_user_id

    profile = get_profile(slack_user_id=slack_user_id, session_id=session_id)
    if self_assign and profile and profile.get("jira_account_id"):
        return ResolveResult(
            account_id=str(profile["jira_account_id"]),
            display_name=str(profile.get("display_name") or ""),
            email=str(profile.get("jira_email") or ""),
            source="profile",
        )

    if not self_assign and profile and name_or_email:
        hint = name_or_email.strip().lower()
        stored_name = str(profile.get("display_name") or "").lower()
        stored_email = str(profile.get("jira_email") or "").lower()
        if hint and (hint == stored_email or hint in stored_name or stored_name.startswith(hint)):
            if profile.get("jira_account_id"):
                return ResolveResult(
                    account_id=str(profile["jira_account_id"]),
                    display_name=str(profile.get("display_name") or ""),
                    email=str(profile.get("jira_email") or ""),
                    source="profile",
                )

    if self_assign and slack_user_id:
        linked = resolve_slack_to_jira(slack_user_id)
        if linked:
            return _from_dict(linked, source="link")

    query = (name_or_email or "").strip()
    if not query and self_assign:
        email = _slack_profile_email(slack_user_id)
        if email:
            query = email

    if _EMAIL_RE.search(query):
        email = normalize_email(_EMAIL_RE.search(query).group(0))  # type: ignore[union-attr]
        contacts = search_contacts(email, limit=5)
        for hit in contacts:
            cid = str(hit.get("id") or "")
            if cid.startswith("jira:"):
                return ResolveResult(
                    account_id=cid.split(":", 1)[1],
                    display_name=str(hit.get("name") or ""),
                    email=email,
                    source="contacts",
                )
        live = search_users(email, max_results=5)
        if len(live) == 1:
            return _from_dict(live[0], source="live")
        if len(live) > 1:
            return ResolveResult(ambiguous=live, source="live")
        return ResolveResult(missing=True, needs_input="jira_email", email=email)

    if query:
        link_matches = resolve_name_to_jira(query)
        if len(link_matches) == 1:
            return _from_dict(link_matches[0], source="link")
        if len(link_matches) > 1:
            return ResolveResult(ambiguous=link_matches, source="link")

        contacts = search_contacts(query, limit=5)
        jira_hits = [c for c in contacts if str(c.get("id") or "").startswith("jira:")]
        if len(jira_hits) == 1:
            cid = jira_hits[0]["id"]
            return ResolveResult(
                account_id=cid.split(":", 1)[1],
                display_name=str(jira_hits[0].get("name") or ""),
                email=str(jira_hits[0].get("email") or ""),
                source="contacts",
            )
        if len(jira_hits) > 1:
            return ResolveResult(
                ambiguous=[
                    {
                        "account_id": h["id"].split(":", 1)[1],
                        "display_name": h.get("name") or "",
                        "email": h.get("email") or "",
                    }
                    for h in jira_hits
                ],
                source="contacts",
            )

        live = search_users(query, max_results=5)
        if len(live) == 1:
            return _from_dict(live[0], source="live")
        if len(live) > 1:
            return ResolveResult(ambiguous=live[:3], source="live")

    if self_assign:
        email = _slack_profile_email(slack_user_id)
        if email:
            return resolve_jira_user(email, slack_user_id=slack_user_id, session_id=session_id)

    return ResolveResult(missing=True, needs_input="jira_email")


def validate_account_id(account_id: str) -> ResolveResult | None:
    user = get_user_by_account_id(account_id)
    if not user:
        return None
    return _from_dict(user, source="live")
