from __future__ import annotations

import json
import logging
import threading
from collections import deque
from pathlib import Path

from tempa.settings import get_settings

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_seen: set[str] = set()
_order: deque[str] = deque(maxlen=5000)
_MAX_AGE_SECONDS = 86400


def _dedupe_path() -> Path:
    path = get_settings().sessions_dir / "whatsapp" / "dedupe.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load() -> None:
    global _seen, _order
    path = _dedupe_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ids = data.get("ids") or []
        if isinstance(ids, list):
            _order = deque((str(i) for i in ids[-5000:]), maxlen=5000)
            _seen = set(_order)
    except Exception as exc:
        logger.warning("Failed to load WhatsApp dedupe store: %s", exc)


def _persist() -> None:
    path = _dedupe_path()
    path.write_text(json.dumps({"ids": list(_order)}, ensure_ascii=False), encoding="utf-8")


def bootstrap() -> None:
    with _lock:
        _load()


def is_seen(key: str) -> bool:
    with _lock:
        if not _order and not _seen:
            _load()
        return key in _seen


def mark_seen(key: str) -> bool:
    """Return True if newly marked, False if duplicate."""
    with _lock:
        if not _order and not _seen:
            _load()
        if key in _seen:
            return False
        _seen.add(key)
        _order.append(key)
        while len(_order) > 5000:
            old = _order.popleft()
            _seen.discard(old)
        _persist()
        return True
