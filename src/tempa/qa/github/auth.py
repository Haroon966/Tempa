"""GitHub App authentication."""

from __future__ import annotations

import logging
import threading
import time

import jwt

from tempa.settings import get_settings

log = logging.getLogger(__name__)

_token_cache: dict[int, dict[str, float | str]] = {}
_cache_lock = threading.Lock()


def _app_id() -> str:
    return get_settings().github_app_id.strip()


def _private_key() -> str:
    return get_settings().github_private_key.replace("\\n", "\n").strip()


def github_configured() -> bool:
    return bool(_app_id() and _private_key())


def get_jwt() -> str:
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 540, "iss": _app_id()}
    token = jwt.encode(payload, _private_key(), algorithm="RS256")
    return token if isinstance(token, str) else token.decode("utf-8")


def get_installation_token(installation_id: int) -> str:
    import httpx

    with _cache_lock:
        cached = _token_cache.get(installation_id)
        if cached and float(cached["expires"]) > time.time() + 300:
            return str(cached["token"])

        app_jwt = get_jwt()
        r = httpx.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=15.0,
        )
        r.raise_for_status()
        data = r.json()
        token = str(data["token"])
        _token_cache[installation_id] = {"token": token, "expires": time.time() + 3000}
        log.info("qa.github.token_fetched installation_id=%s", installation_id)
        return token


def clear_token_cache(installation_id: int | None = None) -> None:
    with _cache_lock:
        if installation_id is not None:
            _token_cache.pop(installation_id, None)
        else:
            _token_cache.clear()
