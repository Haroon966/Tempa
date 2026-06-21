from __future__ import annotations

import json
import re
from pathlib import Path

from tempa.settings import get_settings

_DIGITS_RE = re.compile(r"\D+")


def normalize_phone(number: str) -> str:
    """Normalize to international digits (e.g. 0343… → 92343…)."""
    digits = _DIGITS_RE.sub("", number.strip())
    if not digits:
        return ""
    if digits.startswith("0"):
        return "92" + digits[1:]
    return digits


def _linked_owner_path() -> Path:
    return get_settings().sessions_dir / "whatsapp" / "linked_owner.json"


def _load_linked_owner() -> dict:
    path = _linked_owner_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_linked_owner(*, phone: str, owner_jid: str = "", bridge_only: bool = False) -> str:
    """Persist linked WhatsApp account metadata from the bridge."""
    phone = normalize_phone(phone)
    if not phone:
        return ""
    path = _linked_owner_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_linked_owner()
    data["bridge_phone"] = phone
    data["owner_jid"] = owner_jid or f"{phone}@s.whatsapp.net"
    if not bridge_only:
        data["phone"] = phone
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return phone


async def sync_linked_owner_from_bridge() -> str:
    """Store bridge ownerJid for LID matching; never override WHATSAPP_OWNER_NUMBER."""
    from tempa.debug_agent_log import agent_log

    try:
        from tempa.channels.whatsapp.client import WhatsAppBridgeClient

        inst = await WhatsAppBridgeClient()._instance_row()
        owner_jid = str((inst or {}).get("ownerJid") or "")
        if not owner_jid:
            return get_owner_whatsapp_number()
        phone = normalize_phone(owner_jid.split("@")[0].split(":")[0])
        if phone:
            bridge_only = bool(get_settings().whatsapp_owner_number)
            save_linked_owner(phone=phone, owner_jid=owner_jid, bridge_only=bridge_only)
            agent_log(
                location="numbers.py:sync_linked_owner_from_bridge",
                message="synced bridge owner metadata",
                data={
                    "bridge_phone": phone,
                    "owner_jid": owner_jid,
                    "reply_owner": get_owner_whatsapp_number(),
                },
                hypothesis_id="H6",
            )
            return get_owner_whatsapp_number()
    except Exception:
        pass
    return get_owner_whatsapp_number()


def get_bridge_whatsapp_phone() -> str:
    linked = _load_linked_owner()
    return normalize_phone(str(linked.get("bridge_phone") or ""))


def _remember_lid_phone(lid: str, phone: str) -> None:
    lid = _DIGITS_RE.sub("", lid.split("@")[0].split(":")[0])
    phone = normalize_phone(phone)
    if not lid or not phone:
        return
    data = _load_linked_owner()
    lids = data.get("lid_phones")
    if not isinstance(lids, dict):
        lids = {}
    if lids.get(lid) == phone:
        return
    lids[lid] = phone
    data["lid_phones"] = lids
    path = _linked_owner_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def remember_message_lid_mapping(raw_item: dict | None) -> None:
    """Learn LID → phone mapping when WhatsApp includes remoteJidAlt."""
    if not isinstance(raw_item, dict):
        return
    key = raw_item.get("key")
    if not isinstance(key, dict):
        return
    remote = str(key.get("remoteJid") or "")
    alt = str(key.get("remoteJidAlt") or key.get("participantAlt") or "")
    if remote.endswith("@lid") and alt and "@" in alt:
        lid = remote.split("@")[0].split(":")[0]
        phone = alt.split("@")[0].split(":")[0]
        _remember_lid_phone(lid, phone)


def phones_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return normalize_phone(a) == normalize_phone(b)


def _allowed_extra_path():
    return get_settings().sessions_dir / "whatsapp" / "allowed_reply_numbers.json"


def get_owner_whatsapp_number() -> str:
    settings = get_settings()
    if settings.whatsapp_owner_number:
        return normalize_phone(settings.whatsapp_owner_number)
    linked = _load_linked_owner()
    for key in ("phone", "bridge_phone"):
        value = linked.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_phone(value)
    path = settings.sessions_dir / "whatsapp" / "default_number.txt"
    if path.exists():
        return normalize_phone(path.read_text(encoding="utf-8").strip())
    return ""


def get_extra_allowed_whatsapp_numbers() -> list[str]:
    path = _allowed_extra_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("additional") or data.get("extra") or []
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        primary = get_owner_whatsapp_number()
        for item in raw:
            normalized = normalize_phone(str(item))
            if not normalized or normalized == primary or normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)
        return out
    except Exception:
        return []


def set_extra_allowed_whatsapp_numbers(numbers: list[str]) -> list[str]:
    primary = get_owner_whatsapp_number()
    normalized: list[str] = []
    seen: set[str] = set()
    for item in numbers:
        phone = normalize_phone(str(item).strip())
        if not phone or phone == primary or phone in seen:
            continue
        seen.add(phone)
        normalized.append(phone)
    path = _allowed_extra_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"additional": normalized}, indent=2), encoding="utf-8")
    return normalized


def get_allowed_whatsapp_reply_numbers() -> list[str]:
    primary = get_owner_whatsapp_number()
    bridge = get_bridge_whatsapp_phone()
    extras = get_extra_allowed_whatsapp_numbers()
    out: list[str] = []
    seen: set[str] = set()
    for phone in ([primary] if primary else []) + ([bridge] if bridge else []) + extras:
        if phone and phone not in seen:
            seen.add(phone)
            out.append(phone)
    return out


def is_owner_whatsapp_number(
    number: str,
    *,
    chat_id: str = "",
    raw_item: dict | None = None,
) -> bool:
    allowed = get_allowed_whatsapp_reply_numbers()
    if not allowed:
        return True

    linked = _load_linked_owner()
    owner_jid = str(linked.get("owner_jid") or "")
    lid_phones = linked.get("lid_phones")
    if isinstance(lid_phones, dict):
        for lid_key, mapped_phone in lid_phones.items():
            if not isinstance(mapped_phone, str):
                continue
            lid_digits = _DIGITS_RE.sub("", str(lid_key))
            if lid_digits and lid_digits in {_DIGITS_RE.sub("", number), _DIGITS_RE.sub("", chat_id.split("@")[0])}:
                if any(phones_match(mapped_phone, allowed_number) for allowed_number in allowed):
                    return True

    key = (raw_item or {}).get("key") if isinstance(raw_item, dict) else {}
    if isinstance(key, dict):
        for alt_key in ("remoteJidAlt", "participantAlt"):
            alt = str(key.get(alt_key) or "")
            if alt and "@" in alt:
                alt_phone = normalize_phone(alt.split("@")[0].split(":")[0])
                if any(phones_match(alt_phone, allowed_number) for allowed_number in allowed):
                    return True
        if owner_jid:
            remote = str(key.get("remoteJid") or chat_id or "")
            if remote and (remote == owner_jid or remote.split("@")[0] == owner_jid.split("@")[0]):
                return True

    if chat_id and owner_jid and chat_id == owner_jid:
        return True

    return any(phones_match(number, allowed_number) for allowed_number in allowed)
