from __future__ import annotations

import re
from dataclasses import dataclass

# Common sender typos seen on WhatsApp (expand as needed).
_SENDER_TYPO_CORRECTIONS: dict[str, str] = {
    "hostinfer": "hostinger",
    "hostingr": "hostinger",
    "gogle": "google",
    "googel": "google",
}

_GENERIC_BASES = frozenset({"in:inbox", "is:unread in:inbox", "in:sent"})


@dataclass(frozen=True)
class GmailSearchPlan:
    primary: str
    fallbacks: tuple[str, ...] = ()


def _recent_user_terms(recent_context: list[str] | None) -> list[str]:
    if not recent_context:
        return []
    terms: list[str] = []
    for line in recent_context[-6:]:
        lower = line.lower()
        for pattern in (
            r"from\s+([a-z0-9@.\-_]+)",
            r"related to\s+([a-z0-9@.\-_]+)",
            r"about\s+([a-z0-9@.\-_]+)",
            r"\b(hostinger|google|stripe|aws|github)\b",
        ):
            match = re.search(pattern, lower)
            if not match:
                continue
            term = (match.group(1) if match.lastindex else match.group(0)).strip()
            if len(term) >= 3 and term not in terms:
                terms.append(term)
    return terms


def _time_filter(combined: str) -> str:
    if any(p in combined for p in ("today", "this morning", "this afternoon")):
        return "newer_than:1d"
    if "yesterday" in combined:
        return "newer_than:2d older_than:1d"
    if any(p in combined for p in ("last week", "past week", "this week")):
        return "newer_than:7d"
    if any(p in combined for p in ("last month", "past month", "this month")):
        return "newer_than:30d"
    return ""


def extract_gmail_query(
    task: str,
    user_message: str = "",
    *,
    recent_context: list[str] | None = None,
) -> GmailSearchPlan:
    """Natural language → Gmail `q` string (see Google Gmail search operators)."""
    text = (user_message or task).strip()
    combined = text.lower()

    if "unread" in combined:
        base = "is:unread in:inbox"
    elif re.search(r"\bin\s+sent\b", combined) or (
        "sent" in combined and "inbox" not in combined and "recent" not in combined
    ):
        base = "in:sent"
    else:
        base = "in:inbox"

    extras: list[str] = []
    time_part = _time_filter(combined)
    if time_part:
        extras.append(time_part)

    follow_up_hints = ("more", "again", "those", "them", "that", "same", "else", "another")
    if len(text) < 48 and any(hint in combined for hint in follow_up_hints):
        context_terms = _recent_user_terms(recent_context)
        if context_terms:
            term = context_terms[-1]
            primary = " ".join([base, *extras, term]).strip()
            return GmailSearchPlan(primary=primary, fallbacks=_fallback_queries(primary, term))

    if "attachment" in combined:
        extras.append("has:attachment")
    if "important" in combined:
        extras.append("is:important")

    subject_match = re.search(r"\bsubject[:\s]+([^\n,?]+)", combined, re.I)
    if subject_match:
        subject = subject_match.group(1).strip().strip("\"'")
        if subject:
            extras.append(f"subject:{subject}")

    from_match = re.search(
        r"\b(?:mail|email|e-mail|message)s?\s+from\s+([a-z0-9@.\-_]+)",
        combined,
        re.I,
    )
    if not from_match:
        from_match = re.search(r"\bfrom\s+([a-z0-9@.\-_]+)", combined, re.I)
    if from_match:
        sender = from_match.group(1).strip()
        if sender not in ("me", "myself", "the", "a", "an"):
            primary = " ".join([base, *extras, f"from:{sender}"]).strip()
            return GmailSearchPlan(primary=primary, fallbacks=_fallback_queries(primary, sender))

    topic_match = re.search(
        r"(?:related to|about|regarding|re:|mentioning|containing|with|for)\s+([a-z0-9@.\-_]+)",
        combined,
        re.I,
    )
    if topic_match:
        term = topic_match.group(1).strip()
        if term not in ("me", "my", "the", "a", "an"):
            primary = " ".join([base, *extras, term]).strip()
            return GmailSearchPlan(primary=primary, fallbacks=_fallback_queries(primary, term))

    cleaned = text
    for phrase in (
        "any mail",
        "any email",
        "any e-mail",
        "show me",
        "show my",
        "do i have",
        "is there",
        "are there",
        "can you",
        "please",
        "look for",
        "search for",
        "search",
        "find",
        "get",
        "list",
        "recent",
    ):
        cleaned = re.sub(re.escape(phrase), " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\b(emails?|e-mails?|mail|inbox|gmail|messages?)\b", " ", cleaned, flags=re.I)
    if "unread" in combined:
        cleaned = re.sub(r"\bunread\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    generic = {"", "recent", "my", "the", "a", "an", "some", "all", "latest", "last", "more"}
    if not cleaned or all(part.lower() in generic for part in cleaned.split()):
        primary = " ".join([base, *extras]).strip() or base
        return GmailSearchPlan(primary=primary)

    primary = " ".join([base, *extras, cleaned]).strip()
    return GmailSearchPlan(primary=primary, fallbacks=_fallback_queries(primary, cleaned))


def _fallback_queries(primary: str, term: str) -> tuple[str, ...]:
    fallbacks: list[str] = []
    lower = term.lower()
    corrected = _SENDER_TYPO_CORRECTIONS.get(lower)
    if corrected and corrected != lower:
        fallbacks.append(primary.replace(f"from:{term}", f"from:{corrected}").replace(term, corrected))

    if f"from:{term}" in primary:
        # Broader search if strict from: filter misses (partial domain match).
        base_parts = [p for p in primary.split() if not p.startswith("from:")]
        fallbacks.append(" ".join([*base_parts, term]).strip())

    # Deduplicate while preserving order.
    seen: set[str] = {primary}
    ordered: list[str] = []
    for q in fallbacks:
        if q and q not in seen:
            seen.add(q)
            ordered.append(q)
    return tuple(ordered)


def is_generic_inbox_query(query: str) -> bool:
    return query.strip() in _GENERIC_BASES


def format_query_label(query: str) -> str:
    if is_generic_inbox_query(query):
        return ""
    return query
