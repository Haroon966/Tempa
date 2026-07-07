from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from typing import Any

from tempa.channels.whatsapp.numbers import normalize_phone
from tempa.settings import get_settings

_lock = threading.Lock()


def _peers_path():
    path = get_settings().sessions_dir / "whatsapp" / "peers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_peers() -> dict[str, Any]:
    path = _peers_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_peers(data: dict[str, Any]) -> None:
    _peers_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _name_key(name: str) -> str:
    return " ".join(sorted(w for w in re.split(r"\s+", name.lower()) if len(w) > 1))


def remember_whatsapp_peer(
    *,
    push_name: str = "",
    from_number: str = "",
    chat_id: str = "",
    raw_item: dict[str, Any] | None = None,
) -> None:
    raw = raw_item or {}
    push_name = push_name.strip() or str(raw.get("pushName") or "").strip()
    key = raw.get("key") if isinstance(raw.get("key"), dict) else {}
    chat_id = chat_id or str(key.get("remoteJid") or "")
    if not push_name or not chat_id or "@g.us" in chat_id:
        return
    phone = normalize_phone(from_number or chat_id.split("@")[0].split(":")[0])
    entry = {
        "push_name": push_name,
        "jid": chat_id,
        "phone": phone,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        peers = _load_peers()
        peers[_name_key(push_name)] = entry
        if phone:
            peers[f"phone:{phone}"] = entry
        _save_peers(peers)


def find_whatsapp_peer(name: str) -> dict[str, Any] | None:
    hits = find_all_peers_matching(name)
    return hits[0] if hits else None


def find_all_peers_matching(name: str) -> list[dict[str, Any]]:
    query = name.strip()
    if not query:
        return []
    words = [w for w in re.split(r"\s+", query.lower()) if len(w) > 1]
    with _lock:
        peers = _load_peers()
    if not peers:
        return []

    out: list[dict[str, Any]] = []
    seen_phones: set[str] = set()

    def add(entry: dict[str, Any]) -> None:
        phone = normalize_phone(str(entry.get("phone") or ""))
        if phone and phone in seen_phones:
            return
        if phone:
            seen_phones.add(phone)
        out.append(entry)

    hit = peers.get(_name_key(query))
    if isinstance(hit, dict):
        add(hit)

    for entry in peers.values():
        if not isinstance(entry, dict):
            continue
        push = str(entry.get("push_name") or "").lower()
        if not push:
            continue
        if words and all(w in push for w in words):
            add(entry)
        elif query.lower() in push:
            add(entry)
    return out
