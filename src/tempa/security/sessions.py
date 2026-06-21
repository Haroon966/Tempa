from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_SENSITIVE_FILES = (
    "groq.key",
    "google/token.json",
    "google/storage_state.json",
    "gmail/token.json",
)


def _master_key_path() -> Path:
    return get_settings().sessions_dir / ".master_key"


def _get_fernet():
    from cryptography.fernet import Fernet

    path = _master_key_path()
    if path.exists():
        key = path.read_bytes()
    else:
        key = Fernet.generate_key()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return Fernet(key)


def encrypt_sensitive_sessions() -> int:
    """SEC-01: encrypt sensitive session files at rest."""
    settings = get_settings()
    fernet = _get_fernet()
    encrypted = 0
    for rel in _SENSITIVE_FILES:
        src = settings.sessions_dir / rel
        if not src.exists() or src.suffix == ".enc":
            continue
        dest = src.with_suffix(src.suffix + ".enc")
        try:
            data = src.read_bytes()
            dest.write_bytes(fernet.encrypt(data))
            src.unlink()
            encrypted += 1
        except Exception:
            logger.exception("Failed to encrypt %s", src)
    return encrypted


def decrypt_sensitive_sessions() -> int:
    settings = get_settings()
    fernet = _get_fernet()
    decrypted = 0
    for rel in _SENSITIVE_FILES:
        enc = settings.sessions_dir / f"{rel}.enc"
        if not enc.exists():
            continue
        plain = settings.sessions_dir / rel
        try:
            plain.parent.mkdir(parents=True, exist_ok=True)
            plain.write_bytes(fernet.decrypt(enc.read_bytes()))
            decrypted += 1
        except Exception:
            logger.exception("Failed to decrypt %s", enc)
    return decrypted


def read_secret_file(rel_path: str) -> str:
    settings = get_settings()
    plain = settings.sessions_dir / rel_path
    enc = plain.with_suffix(plain.suffix + ".enc")
    if plain.exists():
        return plain.read_text(encoding="utf-8").strip()
    if enc.exists():
        fernet = _get_fernet()
        return fernet.decrypt(enc.read_bytes()).decode("utf-8").strip()
    return ""


def secret_file_exists(rel_path: str) -> bool:
    settings = get_settings()
    plain = settings.sessions_dir / rel_path
    enc = plain.with_suffix(plain.suffix + ".enc")
    return plain.exists() or enc.exists()


def delete_secret_file(rel_path: str) -> None:
    settings = get_settings()
    plain = settings.sessions_dir / rel_path
    enc = plain.with_suffix(plain.suffix + ".enc")
    for path in (plain, enc):
        if path.exists():
            path.unlink()


def write_secret_file(rel_path: str, content: str, *, encrypt: bool = True) -> None:
    settings = get_settings()
    path = settings.sessions_dir / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if encrypt:
        fernet = _get_fernet()
        enc = path.with_suffix(path.suffix + ".enc")
        enc.write_bytes(fernet.encrypt(content.encode("utf-8")))
        if path.exists():
            path.unlink()
    else:
        path.write_text(content, encoding="utf-8")
