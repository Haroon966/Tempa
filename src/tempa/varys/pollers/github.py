from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

from tempa.qa.github.auth import get_github_token, github_configured
from tempa.varys.config import load_varys_config

logger = logging.getLogger(__name__)


def _repo_slugs() -> list[str]:
    cfg = load_varys_config()
    slugs: list[str] = []
    for entry in cfg.repos:
        if isinstance(entry, str):
            slug = entry.strip()
        elif isinstance(entry, dict):
            slug = str(entry.get("repo") or entry.get("slug") or "").strip()
        else:
            continue
        if slug and "/" in slug:
            slugs.append(slug.rstrip("/"))
    return slugs


def _parse_github_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_updated_pulls(repo: str, *, since_iso: str, token: str) -> list[dict[str, Any]]:
    since = _parse_github_time(since_iso)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "tempa-varys",
    }
    pulls: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                f"https://api.github.com/repos/{repo}/pulls",
                headers=headers,
                params={"state": "open", "sort": "updated", "direction": "desc", "per_page": 20},
            )
            if resp.status_code != 200:
                logger.warning("GitHub pulls for %s returned %s", repo, resp.status_code)
                return []
            for pr in resp.json():
                updated = _parse_github_time(str(pr.get("updated_at") or ""))
                if since and updated and updated <= since:
                    break
                pulls.append(
                    {
                        "repo": repo,
                        "number": pr.get("number"),
                        "title": pr.get("title", ""),
                        "state": pr.get("state", ""),
                        "url": pr.get("html_url", ""),
                        "updated_at": pr.get("updated_at", ""),
                        "user": (pr.get("user") or {}).get("login", ""),
                    }
                )
    except Exception as exc:
        logger.warning("GitHub PR fetch failed for %s: %s", repo, exc)
    return pulls


def poll_repos(since_iso: str) -> list[dict[str, Any]]:
    if not github_configured():
        return []
    repos = _repo_slugs()
    if not repos:
        return []
    events: list[dict[str, Any]] = []
    for repo in repos:
        try:
            token = get_github_token(repo)
        except RuntimeError:
            logger.debug("No GitHub token for repo %s", repo)
            continue
        for pr in fetch_updated_pulls(repo, since_iso=since_iso, token=token):
            events.append(pr)
    return events
