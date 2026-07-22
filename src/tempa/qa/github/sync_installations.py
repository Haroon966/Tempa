"""Refresh GitHub App installations into the local registry."""

from __future__ import annotations

import logging

import httpx

from tempa.qa.github.auth import get_installation_token, get_jwt, github_auth_mode
from tempa.qa.installations import upsert_installation

log = logging.getLogger(__name__)


def sync_app_installations() -> int:
    """Fetch App installations + repos from GitHub and upsert locally. Returns installation count."""
    if github_auth_mode() not in ("app", "pat"):
        # App credentials may still be present alongside a PAT.
        pass
    try:
        app_jwt = get_jwt()
    except Exception as exc:
        log.info("qa.github.sync skipped (no app jwt): %s", exc)
        return 0

    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "tempa",
    }
    synced = 0
    with httpx.Client(timeout=30.0) as client:
        resp = client.get("https://api.github.com/app/installations", headers=headers)
        if resp.status_code != 200:
            log.warning("qa.github.sync installations failed: %s %s", resp.status_code, resp.text[:200])
            return 0
        for inst in resp.json() or []:
            iid = int(inst.get("id") or 0)
            account = str((inst.get("account") or {}).get("login") or "")
            if not iid:
                continue
            try:
                token = get_installation_token(iid)
            except Exception as exc:
                log.warning("qa.github.sync token failed for %s: %s", iid, exc)
                continue
            repo_headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "tempa",
            }
            repos: list[dict] = []
            page = 1
            while page <= 10:
                rr = client.get(
                    "https://api.github.com/installation/repositories",
                    headers=repo_headers,
                    params={"per_page": 100, "page": page},
                )
                if rr.status_code != 200:
                    break
                batch = rr.json().get("repositories") or []
                for r in batch:
                    repos.append({"full_name": r.get("full_name"), "id": r.get("id")})
                if len(batch) < 100:
                    break
                page += 1
            upsert_installation(iid, account, repos)
            synced += 1
            log.info("qa.github.sync installation=%s account=%s repos=%s", iid, account, len(repos))
    return synced
