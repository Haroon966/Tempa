from __future__ import annotations

import json
import re

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
    extras = get_extra_allowed_whatsapp_numbers()
    out: list[str] = []
    seen: set[str] = set()
    for phone in ([primary] if primary else []) + extras:
        if phone and phone not in seen:
            seen.add(phone)
            out.append(phone)
    return out


def is_owner_whatsapp_number(number: str) -> bool:
    allowed = get_allowed_whatsapp_reply_numbers()
    if not allowed:
        return True
    return any(phones_match(number, allowed_number) for allowed_number in allowed)
