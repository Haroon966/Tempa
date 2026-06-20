from __future__ import annotations

import json
import secrets
import socket
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tempa.settings import get_settings

_lock = threading.Lock()
_active_tokens: dict[str, dict[str, Any]] = {}


def _load_transfer_config() -> dict[str, Any]:
    try:
        import yaml

        path = get_settings().config_dir / "permissions.yaml"
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("transfer") or {}
    except Exception:
        return {}


def _token_ttl() -> int:
    return int(_load_transfer_config().get("token_ttl_seconds", 300))


def _max_file_bytes() -> int:
    mb = int(_load_transfer_config().get("max_file_mb", 100))
    return mb * 1024 * 1024


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def create_transfer_token(file_path: str) -> dict[str, Any]:
    path = Path(file_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        return {"status": "error", "reason": "File not found"}
    size = path.stat().st_size
    if size > _max_file_bytes():
        return {"status": "error", "reason": f"File exceeds max size ({size} bytes)"}

    token = secrets.token_urlsafe(16)
    cfg = _load_transfer_config()
    port = int(cfg.get("port", 8788))
    host = _local_ip()
    expires = datetime.now(timezone.utc) + timedelta(seconds=_token_ttl())

    record = {
        "token": token,
        "path": str(path),
        "filename": path.name,
        "size": size,
        "expires_at": expires.isoformat(),
        "downloads_remaining": 3,
    }
    with _lock:
        _active_tokens[token] = record

    url = f"http://{host}:{port}/download/{token}"
    qr_data = url
    try:
        import qrcode
        import io
        import base64

        img = qrcode.make(qr_data)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        qr_image = f"data:image/png;base64,{qr_b64}"
    except Exception:
        qr_image = None

    return {
        "status": "ready",
        "token": token,
        "url": url,
        "qr_data": qr_data,
        "qr_image": qr_image,
        "filename": path.name,
        "size": size,
        "expires_at": expires.isoformat(),
    }


def consume_token(token: str) -> dict[str, Any] | None:
    with _lock:
        record = _active_tokens.get(token)
        if not record:
            return None
        try:
            exp = datetime.fromisoformat(record["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= exp:
                _active_tokens.pop(token, None)
                return None
        except Exception:
            pass
        remaining = int(record.get("downloads_remaining", 1))
        if remaining <= 0:
            _active_tokens.pop(token, None)
            return None
        record["downloads_remaining"] = remaining - 1
        if record["downloads_remaining"] <= 0:
            _active_tokens.pop(token, None)
        return dict(record)


async def activate_transfer(file_path: str) -> dict[str, Any]:
    from tempa.pc.transfer.server import ensure_transfer_server

    await ensure_transfer_server()
    return create_transfer_token(file_path)
