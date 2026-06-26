"""GitHub authentication — PAT or GitHub App."""

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


def _pat_token() -> str:
    return get_settings().github_token.strip()


def github_uses_pat() -> bool:
    return bool(_pat_token())


def github_configured() -> bool:
    return bool(_pat_token() or (_app_id() and _private_key()))


def github_auth_mode() -> str | None:
    if github_uses_pat():
        return "pat"
    if _app_id() and _private_key():
        return "app"
    return None


def get_github_token(repo: str | None = None) -> str:
    if pat := _pat_token():
        return pat
    from tempa.qa.installations import installation_id_for_repo

    inst_id = installation_id_for_repo(repo) if repo else None
    if inst_id:
        return get_installation_token(inst_id)
    raise RuntimeError("No GitHub token configured")


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
