"""Tests for GitHub webhook verification."""

import hashlib
import hmac
import json

import pytest

from tempa.qa.webhook import verify_signature, verify_webhook_request


@pytest.fixture
def webhook_secret(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-webhook-secret-32chars-min")
    from tempa.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _sign(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_verify_signature_valid(webhook_secret):
    payload = b'{"action":"opened"}'
    sig = _sign(payload, "test-webhook-secret-32chars-min")
    assert verify_signature(payload, sig) is True


def test_verify_signature_invalid(webhook_secret):
    assert verify_signature(b"{}", "sha256=bad") is False


def test_verify_webhook_request(webhook_secret):
    payload = json.dumps({"repository": {"full_name": "o/r"}}).encode()
    secret = "test-webhook-secret-32chars-min"
    ok, err = verify_webhook_request(
        payload_bytes=payload,
        headers={"X-Hub-Signature-256": _sign(payload, secret)},
        client_ip="127.0.0.1",
    )
    assert ok is True
    assert err == ""
