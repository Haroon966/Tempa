from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from typing import Any

from tempa.settings import get_settings

_last_request_at = 0.0
_MIN_INTERVAL = 0.35


def notion_configured() -> bool:
    settings = get_settings()
    return bool(settings.notion_api_key.strip() and settings.notion_harness_db_id.strip())


def notion_request(req: urllib.request.Request) -> tuple[int, str]:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        _last_request_at = time.monotonic()
        return resp.status, body


def fetch_page(page_id: str) -> dict[str, Any]:
    import json

    settings = get_settings()
    api_key = settings.notion_api_key.strip()
    req = urllib.request.Request(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": "2022-06-28",
        },
        method="GET",
    )
    try:
        _, body = notion_request(req)
        return json.loads(body)
    except (urllib.error.URLError, json.JSONDecodeError):
        return {}


def _notion_headers() -> dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.notion_api_key.strip()}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def _plain_text(prop: dict[str, Any]) -> str:
    prop_type = prop.get("type", "")
    if prop_type == "title":
        parts = prop.get("title") or []
    elif prop_type == "rich_text":
        parts = prop.get("rich_text") or []
    elif prop_type == "select":
        sel = prop.get("select") or {}
        return str(sel.get("name") or "")
    elif prop_type == "status":
        st = prop.get("status") or {}
        return str(st.get("name") or "")
    else:
        return ""
    return "".join(part.get("plain_text", "") for part in parts).strip()


def _page_summary(page: dict[str, Any]) -> dict[str, Any]:
    props = page.get("properties") or {}
    title = ""
    status = ""
    for _key, prop in props.items():
        if not isinstance(prop, dict):
            continue
        if prop.get("type") == "title" and not title:
            title = _plain_text(prop)
        elif prop.get("type") in {"status", "select"} and not status:
            status = _plain_text(prop)
    return {
        "id": page.get("id", ""),
        "title": title or "(untitled)",
        "status": status,
        "url": page.get("url", ""),
        "last_edited_time": page.get("last_edited_time", ""),
    }


def query_harness_database(*, since_iso: str) -> list[dict[str, Any]]:
    """Return harness DB pages edited after since_iso (ISO-8601)."""
    import json

    settings = get_settings()
    db_id = settings.notion_harness_db_id.strip()
    if not db_id:
        return []

    body = {
        "filter": {
            "timestamp": "last_edited_time",
            "last_edited_time": {"after": since_iso},
        },
        "sorts": [{"timestamp": "last_edited_time", "direction": "ascending"}],
        "page_size": 50,
    }
    req = urllib.request.Request(
        f"https://api.notion.com/v1/databases/{db_id}/query",
        data=json.dumps(body).encode("utf-8"),
        headers=_notion_headers(),
        method="POST",
    )
    try:
        _, raw = notion_request(req)
        data = json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        logging.getLogger(__name__).warning("Notion harness query failed: %s", exc)
        return []

    pages: list[dict[str, Any]] = []
    for result in data.get("results") or []:
        if result.get("object") == "page":
            pages.append(_page_summary(result))
    return pages
