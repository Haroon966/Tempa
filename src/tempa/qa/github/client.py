"""GitHub REST API client with retries."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
DEFAULT_TIMEOUT = 20.0
MAX_RETRIES = 3


class GitHubError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _handle_response(r: httpx.Response, method: str, path: str) -> Any:
    if r.status_code in (200, 201):
        return r.json() if r.content else {}
    if r.status_code == 204:
        return {}

    if r.status_code == 429:
        retry_after = int(r.headers.get("Retry-After", "30"))
        raise GitHubError(f"Primary rate limit — retry after {retry_after}s", 429)

    if r.status_code == 403:
        try:
            body = r.json()
            msg = str(body.get("message", "")).lower()
            if "secondary rate limit" in msg or "abuse" in msg:
                time.sleep(60)
                raise GitHubError("Secondary rate limit — waited 60s, retry now", 403)
            raise GitHubError(f"Forbidden: {body.get('message', 'no message')}", 403)
        except GitHubError:
            raise
        except Exception:
            raise GitHubError(f"403 Forbidden: {path}", 403)

    if r.status_code == 404:
        raise GitHubError(f"Not found: {path}", 404)

    if r.status_code == 422:
        try:
            detail = r.json().get("message", "Unprocessable Entity")
        except Exception:
            detail = "Unprocessable Entity"
        raise GitHubError(f"422 Unprocessable: {detail}", 422)

    if r.status_code >= 500:
        raise GitHubError(f"GitHub server error {r.status_code}: {path}", r.status_code)

    raise GitHubError(f"{method} {path} → {r.status_code}: {r.text[:200]}", r.status_code)


def _request(method: str, path: str, token: str, *, json: dict | None = None) -> Any:
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
                r = client.request(method, url, headers=_headers(token), json=json)
            if r.status_code in (502, 503, 504) and attempt < MAX_RETRIES - 1:
                time.sleep(0.5 * (2**attempt))
                continue
            return _handle_response(r, method, path)
        except httpx.RequestError as exc:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(0.5 * (2**attempt))
                continue
            raise GitHubError(f"Connection error: {exc}", 0) from exc
    if last_exc:
        raise GitHubError(f"Connection error: {last_exc}", 0) from last_exc
    raise GitHubError(f"Request failed: {path}", 0)


def gh_get(path: str, token: str) -> Any:
    return _request("GET", path, token)


def gh_get_all(path: str, token: str, max_pages: int = 5) -> list[Any]:
    results: list[Any] = []
    sep = "&" if "?" in path else "?"
    for page in range(1, max_pages + 1):
        paged = f"{path}{sep}page={page}&per_page=100"
        try:
            data = gh_get(paged, token)
        except GitHubError as exc:
            log.warning("gh_get_all stopped at page=%s: %s", page, exc)
            break
        if not data:
            break
        if isinstance(data, list):
            results.extend(data)
            if len(data) < 100:
                break
        else:
            return [data]
    return results


def gh_post(path: str, token: str, data: dict[str, Any]) -> Any:
    return _request("POST", path, token, json=data)


def gh_put(path: str, token: str, data: dict[str, Any]) -> Any:
    return _request("PUT", path, token, json=data)


def gh_patch(path: str, token: str, data: dict[str, Any]) -> Any:
    return _request("PATCH", path, token, json=data)


def gh_delete(path: str, token: str) -> Any:
    return _request("DELETE", path, token)
