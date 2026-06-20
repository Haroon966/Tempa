from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from tempa.router.groq_router import get_router


def _parse_relative_date(text: str) -> tuple[str | None, str | None]:
    """Heuristic date range extraction from natural language."""
    lower = text.lower()
    now = datetime.now(timezone.utc)
    if "today" in lower:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.isoformat(), now.isoformat()
    if "yesterday" in lower:
        start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return start.isoformat(), end.isoformat()
    if "last week" in lower:
        return (now - timedelta(days=7)).isoformat(), now.isoformat()
    if "last month" in lower:
        return (now - timedelta(days=30)).isoformat(), now.isoformat()
    weekday_match = re.search(
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        lower,
    )
    if weekday_match:
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        target = days.index(weekday_match.group(1))
        current = now.weekday()
        delta = (current - target) % 7 or 7
        day = (now - timedelta(days=delta)).replace(hour=0, minute=0, second=0, microsecond=0)
        return day.isoformat(), (day + timedelta(days=1)).isoformat()
    return None, None


def extract_filters_from_query(query: str) -> dict[str, Any]:
    """Extract metadata filters from a natural language memory query."""
    filters: dict[str, Any] = {}
    lower = query.lower()

    if "meet" in lower or "standup" in lower:
        filters["tool"] = "meet"
    elif any(k in lower for k in ("gmail", "email", "inbox")):
        filters["tool"] = "gmail"
    elif "calendar" in lower or "schedule" in lower:
        filters["tool"] = "calendar"
    elif "whatsapp" in lower:
        filters["tool"] = "whatsapp"

    date_from, date_to = _parse_relative_date(query)
    if date_from:
        filters["date_from"] = date_from
    if date_to:
        filters["date_to"] = date_to

    email_match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", query)
    if email_match:
        filters["participant"] = email_match.group(0)

    phone_match = re.search(r"\+?\d{10,15}", query)
    if phone_match and "participant" not in filters:
        filters["participant"] = phone_match.group(0)

    for tag in ("action-item", "minutes", "preference", "semantic"):
        if tag.replace("-", " ") in lower or tag in lower:
            filters.setdefault("tags", []).append(tag)

    try:
        router = get_router()
        if not router.api_key:
            return filters
        response = router.chat_completion(
            category="reasoning",
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Extract memory search filters from the query. Return JSON only with optional keys: "
                        'tool (whatsapp|meet|calendar|gmail|pc|procedural), date_from (ISO), date_to (ISO), '
                        'participant (email or phone), tags (string array). Use null for missing fields.\n\n'
                        f"Query: {query}"
                    ),
                }
            ],
            response_format={"type": "json_object"},
            max_tokens=256,
            temperature=0.0,
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            for key in ("tool", "date_from", "date_to", "participant"):
                val = parsed.get(key)
                if val and key not in filters:
                    filters[key] = val
            llm_tags = parsed.get("tags")
            if isinstance(llm_tags, list):
                filters["tags"] = list({*(filters.get("tags") or []), *llm_tags})
    except Exception:
        pass

    return filters
