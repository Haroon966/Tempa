"""Ensure Playwright can read Meet browser auth (plain or encrypted)."""

from __future__ import annotations

import json
from pathlib import Path

from tempa.security.sessions import read_secret_file, secret_file_exists, write_secret_file
from tempa.settings import get_settings


def storage_state_is_valid(raw: str | bytes | None) -> bool:
    """True when payload looks like a signed-in Playwright storage_state."""
    if not raw:
        return False
    try:
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        data = json.loads(text)
    except (TypeError, ValueError, UnicodeDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    cookies = data.get("cookies")
    if not isinstance(cookies, list) or not cookies:
        return False
    return any(
        isinstance(c, dict)
        and c.get("name") in ("SID", "__Secure-1PSID", "__Secure-3PSID", "SAPISID")
        for c in cookies
    )


def meet_auth_ready() -> bool:
    """Whether Meet browser auth is present and usable (not just an empty file)."""
    if not secret_file_exists("google/storage_state.json"):
        return False
    settings = get_settings()
    plain = settings.google_storage_state_path
    if plain.exists() and plain.stat().st_size > 0:
        try:
            return storage_state_is_valid(plain.read_text(encoding="utf-8"))
        except OSError:
            return False
    return storage_state_is_valid(read_secret_file("google/storage_state.json"))


def materialize_storage_state_path() -> str | None:
    """Return a plaintext storage_state.json path for Playwright, or None.

    SEC encrypts this file at rest (deletes plain on shutdown). Always
    rematerialize from .enc before join/readiness so a shutdown race or
    missing plain does not look like 'run meet-auth'.
    """
    if not secret_file_exists("google/storage_state.json"):
        return None
    settings = get_settings()
    plain = settings.google_storage_state_path
    if plain.exists() and plain.stat().st_size > 0:
        try:
            if storage_state_is_valid(plain.read_text(encoding="utf-8")):
                return str(plain)
        except OSError:
            pass
    raw = read_secret_file("google/storage_state.json")
    if not storage_state_is_valid(raw):
        return None
    plain.parent.mkdir(parents=True, exist_ok=True)
    plain.write_text(raw, encoding="utf-8")
    return str(plain)


def save_storage_state_json(raw: str, *, encrypt: bool = True) -> Path:
    """Persist Meet auth; rejects empty/guest payloads."""
    if not storage_state_is_valid(raw):
        raise ValueError("storage_state missing Google session cookies; run tempa meet-auth again")
    write_secret_file("google/storage_state.json", raw, encrypt=encrypt)
    settings = get_settings()
    plain = settings.google_storage_state_path
    plain.parent.mkdir(parents=True, exist_ok=True)
    plain.write_text(raw, encoding="utf-8")
    return plain
