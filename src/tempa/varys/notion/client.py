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
