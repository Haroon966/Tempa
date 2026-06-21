from __future__ import annotations

import logging
import re
from typing import Any

from tempa.channels.contacts.gmail_extract import _parse_address_header
from tempa.channels.gmail.compose import is_valid_recipient_email
from tempa.channels.gmail.oauth import load_gmail_client

logger = logging.getLogger(__name__)

_BLOCKED_GUEST_LOCALS = frozenset(
    {
        "notifications",
        "noreply",
        "no-reply",
        "donotreply",
        "mailer-daemon",
        "postmaster",
    }
)
_BLOCKED_GUEST_DOMAINS = frozenset(
    {
        "github.com",
        "gitlab.com",
        "linkedin.com",
        "facebookmail.com",
    }
)

_SEND_TO_PATTERNS = (
    re.compile(
        r"send(?:\s+an?\s+email|\s+mail|\s+a\s+mail)?\s+to\s+(.+?)(?:\s+about|\s+regarding|\s+that|\s+saying|$)",
        re.I,
    ),
    re.compile(r"send\s+(.+?)\s+an?\s+(?:email|mail)(?:\s+about|\s+regarding|\s+that|$)", re.I),
    re.compile(r"write(?:\s+an?\s+email|\s+mail)?\s+to\s+(.+?)(?:\s+about|\s+regarding|$)", re.I),
    re.compile(r"(?:^|\s)email\s+(.+?)(?:\s+about|\s+regarding|\s+that|\s+saying|$)", re.I),
)


def extract_recipient_name(text: str) -> str:
    text = text.strip()
    if not text or "@" in text:
        return ""
    for pattern in _SEND_TO_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        name = match.group(1).strip(" .,\"'")
        if not name or "@" in name:
            continue
        lower = name.lower()
        if lower in {"mail", "email", "a mail", "an email"}:
            continue
        return name
    return ""


def _name_match_score(query: str, candidate: str) -> int:
    query_norm = " ".join(query.lower().split())
    candidate_norm = " ".join(candidate.lower().split())
    if not query_norm or not candidate_norm:
        return 0
    if query_norm == candidate_norm:
        return 100
    query_words = query_norm.split()
    if all(word in candidate_norm for word in query_words):
        return 85
    candidate_words = candidate_norm.split()
    if all(any(word in cand or cand.startswith(word) for cand in candidate_words) for word in query_words):
        return 70
    return 0


def _email_local_name_score(name: str, email: str) -> int:
    local = email.split("@", 1)[0].lower()
    parts = [part for part in re.split(r"[._+\-]", name.lower()) if len(part) > 1]
    if not parts:
        return 0
    if all(part in local for part in parts):
        return 45
    if any(part in local for part in parts):
        return 25
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
        if last in local and first[1:] in local:
            return 40
        if last in local and first[:-1] in local:
            return 40
    return 0


def _guess_email_addresses(name: str) -> list[str]:
    parts = [part for part in name.split() if part]
    if len(parts) < 2:
        return []
    local = f"{parts[0]}.{parts[1]}".lower()
    from tempa.channels.contacts.store import search_contacts

    domains: set[str] = set()
    for query in (parts[-1], parts[0], " ".join(parts), local):
        for hit in search_contacts(query, limit=25):
            email = str(hit.get("email", "")).strip().lower()
            if "@" in email:
                domains.add(email.split("@", 1)[1])
    return [f"{local}@{domain}" for domain in sorted(domains)]


def _verified_guess_emails(name: str, *, owner: str = "") -> list[str]:
    client = load_gmail_client()
    if client is None:
        return []
    verified: list[str] = []
    for guess in _guess_email_addresses(name):
        if is_excluded_guest_email(guess, owner=owner):
            continue
        try:
            message_ids, _ = client.list_messages(query=f"to:{guess}", max_results=1)
        except Exception:
            continue
        if message_ids and guess not in verified:
            verified.append(guess)
    return verified


def is_excluded_guest_email(email: str, *, owner: str = "") -> bool:
    """True for invalid, automated, or calendar-owner addresses — not real guests."""
    if not is_valid_recipient_email(email):
        return True
    lower = email.strip().lower()
    if owner and lower == owner.strip().lower():
        return True
    local, _, domain = lower.partition("@")
    if not local or not domain:
        return True
    if local in _BLOCKED_GUEST_LOCALS or local.startswith("noreply"):
        return True
    if domain in _BLOCKED_GUEST_DOMAINS:
        return True
    return False


def _score_address(name: str, display_name: str, email: str) -> int:
    if not is_valid_recipient_email(email):
        return 0
    name_score = _name_match_score(name, display_name)
    local_score = _email_local_name_score(name, email)
    if name_score <= 0 and local_score <= 0:
        return 0
    # Prefer addresses where the email local part matches the name, not just display name.
    if local_score <= 0 and name_score > 0:
        return max(10, name_score // 4)
    return name_score + local_score


def lookup_email_by_name_in_gmail(
    name: str,
    *,
    max_messages: int = 25,
    owner: str = "",
) -> dict[str, str]:
    """Find a recipient email by searching Gmail From/To headers for a person's name."""
    query_name = name.strip()
    if not query_name or "@" in query_name:
        return {}

    client = load_gmail_client()
    if client is None:
        return {}

    queries = [f'"{query_name}"', f"from:{query_name}", f"to:{query_name}"]
    parts = query_name.split()
    if len(parts) >= 2:
        local_guess = f"{parts[0]}.{parts[1]}".lower()
        queries.extend(
            [
                f"from:{parts[0]}",
                f"to:{parts[0]}",
                f"to:{local_guess}",
                f"from:{local_guess}",
                local_guess,
            ]
        )

    seen_ids: set[str] = set()
    scores: dict[str, int] = {}
    names: dict[str, str] = {}

    for query in queries:
        try:
            message_ids, _ = client.list_messages(query=query, max_results=max_messages)
        except Exception:
            logger.debug("Gmail recipient lookup query failed: %s", query)
            continue

        for message_id in message_ids:
            if message_id in seen_ids:
                continue
            seen_ids.add(message_id)
            try:
                message = client.get_message_metadata(message_id)
            except Exception:
                logger.debug("Skipping message %s during recipient lookup", message_id)
                continue

            for header in (message.sender, message.to):
                for row in _parse_address_header(header):
                    email = row["email"]
                    if is_excluded_guest_email(email, owner=owner):
                        continue
                    score = _score_address(query_name, row.get("name", ""), email)
                    if score <= 0:
                        continue
                    scores[email] = max(scores.get(email, 0), score)
                    display = row.get("name", "").strip()
                    if display and (email not in names or len(display) > len(names[email])):
                        names[email] = display

    if not scores:
        return {}

    best_email = max(scores, key=lambda address: (scores[address], names.get(address, "")))
    return {
        "email": best_email,
        "name": names.get(best_email, query_name),
        "source": "gmail",
    }


def resolve_guest_email_by_name(name: str, *, owner: str = "") -> str:
    """Resolve a guest email from contacts and Gmail, excluding the calendar owner."""
    query_name = name.strip()
    if not query_name:
        return ""
    if "@" in query_name:
        email = query_name.strip()
        return "" if is_excluded_guest_email(email, owner=owner) else email

    from tempa.channels.contacts.store import search_contacts
    from tempa.channels.contacts.sync import sync_contacts_blocking

    best_email = ""
    best_score = 0

    for guess in _verified_guess_emails(query_name, owner=owner):
        score = _score_address(query_name, query_name, guess) + 60
        if score > best_score:
            best_score = score
            best_email = guess

    for hit in search_contacts(query_name, limit=10):
        email = str(hit.get("email", "")).strip()
        if is_excluded_guest_email(email, owner=owner):
            continue
        score = _score_address(query_name, str(hit.get("name", "")), email)
        if score > best_score:
            best_score = score
            best_email = email

    gmail_hint = lookup_email_by_name_in_gmail(query_name, owner=owner)
    gmail_email = str(gmail_hint.get("email", "")).strip()
    if gmail_email and not is_excluded_guest_email(gmail_email, owner=owner):
        gmail_score = _score_address(query_name, str(gmail_hint.get("name", "")), gmail_email)
        if gmail_score > best_score:
            best_email = gmail_email

    if best_email:
        return best_email

    sync_contacts_blocking()
    for hit in search_contacts(query_name, limit=10):
        email = str(hit.get("email", "")).strip()
        if is_excluded_guest_email(email, owner=owner):
            continue
        score = _score_address(query_name, str(hit.get("name", "")), email)
        if score > best_score:
            best_score = score
            best_email = email

    gmail_hint = lookup_email_by_name_in_gmail(query_name, owner=owner)
    gmail_email = str(gmail_hint.get("email", "")).strip()
    if gmail_email and not is_excluded_guest_email(gmail_email, owner=owner):
        gmail_score = _score_address(query_name, str(gmail_hint.get("name", "")), gmail_email)
        if gmail_score > best_score:
            best_email = gmail_email

    return best_email


def build_gmail_search_queries(name: str) -> list[str]:
    queries = [f'"{name}"', f"from:{name}", f"to:{name}"]
    parts = name.split()
    if len(parts) >= 2:
        queries.extend([f"from:{parts[0]}", f"to:{parts[0]}"])
    return queries
