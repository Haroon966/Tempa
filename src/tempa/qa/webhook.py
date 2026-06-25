"""Webhook verification and idempotency."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from tempa.qa.config import qa_data_dir
from tempa.settings import get_settings

log = logging.getLogger(__name__)

MAX_PAYLOAD_BYTES = 25 * 1024 * 1024
MAX_AGE_SECONDS = 300
IP_RATE_LIMIT = 100

_ip_counts: dict[str, list[float]] = {}
_ip_lock = threading.Lock()
_seen_lock = threading.Lock()


def _webhook_secret() -> bytes:
    return get_settings().github_webhook_secret.encode()


def webhook_configured() -> bool:
    return bool(get_settings().github_webhook_secret.strip())


def verify_signature(payload_bytes: bytes, signature_header: str) -> bool:
    secret = _webhook_secret()
    if not secret:
        log.error("qa.webhook.no_secret — rejecting")
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret, payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def verify_timestamp(headers: dict[str, str]) -> bool:
    ts_header = headers.get("X-GitHub-Event-Time") or headers.get("X-Timestamp")
    if not ts_header:
        return True
    try:
        event_ts = int(ts_header)
        age = time.time() - event_ts
        if age > MAX_AGE_SECONDS or age < -30:
            return False
    except (ValueError, TypeError):
        pass
    return True


def check_ip_rate_limit(ip: str) -> bool:
    now = time.time()
    with _ip_lock:
        window = [t for t in _ip_counts.get(ip, []) if now - t < 60]
        window.append(now)
        _ip_counts[ip] = window
        return len(window) <= IP_RATE_LIMIT


def _seen_path() -> Path:
    p = qa_data_dir() / "webhook_seen.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def is_duplicate_delivery(delivery_id: str) -> bool:
    if not delivery_id:
        return False
    with _seen_lock:
        path = _seen_path()
        seen: dict[str, float] = {}
        if path.exists():
            try:
                seen = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                seen = {}
        now = time.time()
        seen = {k: v for k, v in seen.items() if now - v < 3600}
        if delivery_id in seen:
            return True
        seen[delivery_id] = now
        path.write_text(json.dumps(seen), encoding="utf-8")
        return False


def is_bot_sender(payload: dict[str, Any]) -> bool:
    sender = payload.get("sender") or {}
    sender_type = str(sender.get("type") or "")
    sender_login = str(sender.get("login") or "")
    if sender_type.lower() == "bot":
        return True
    if sender_login.endswith("[bot]"):
        return True
    return False


def verify_webhook_request(
    *,
    payload_bytes: bytes,
    headers: dict[str, str],
    client_ip: str,
) -> tuple[bool, str]:
    if len(payload_bytes) > MAX_PAYLOAD_BYTES:
        return False, "Payload too large"
    if not check_ip_rate_limit(client_ip):
        return False, "Too many requests"
    sig = headers.get("X-Hub-Signature-256", "")
    if not verify_signature(payload_bytes, sig):
        return False, "Invalid signature"
    if not verify_timestamp(headers):
        return False, "Webhook too old or timestamp invalid"
    delivery_id = headers.get("X-GitHub-Delivery", "")
    if is_duplicate_delivery(delivery_id):
        return False, "Duplicate delivery"
    return True, ""
