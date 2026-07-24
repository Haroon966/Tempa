"""Cursor SDK provider for deep PR reviews and Slack thread answers."""

from __future__ import annotations

import asyncio
import logging
import re

from tempa.settings import get_settings

log = logging.getLogger(__name__)

_GITHUB_SLUG_RE = re.compile(
    r"(?:https?://github\.com/)?(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?/?$",
    re.I,
)


def cursor_configured() -> bool:
    return bool(get_settings().cursor_api_key.strip())


def _repo_slug(repo: str) -> str:
    raw = (repo or "").strip()
    if not raw:
        return ""
    m = _GITHUB_SLUG_RE.match(raw.rstrip("/"))
    if m:
        return f"{m.group('owner')}/{m.group('repo')}"
    # Already owner/repo (or close enough).
    parts = raw.replace("https://github.com/", "").strip("/").split("/")
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1].removesuffix('.git')}"
    return raw


def resolve_cloud_starting_ref(repo: str, starting_ref: str | None = None) -> str:
    """Concrete ref for Cursor cloud — never leave unset (SDK fails without it)."""
    ref = (starting_ref or "").strip()
    if ref:
        return ref
    slug = _repo_slug(repo)
    if slug and "/" in slug:
        try:
            from tempa.qa.github.auth import get_github_token
            from tempa.qa.github.client import gh_get

            token = get_github_token(slug)
            if token:
                branch = str(gh_get(f"/repos/{slug}", token).get("default_branch") or "").strip()
                if branch:
                    return branch
        except Exception:
            log.warning("could not resolve default branch for %s — using main", slug)
    return "main"


def _prompt_sync(
    prompt: str,
    *,
    repo: str = "",
    starting_ref: str | None = None,
    local_cwd: str = "",
    auto_create_pr: bool = False,
) -> str:
    from cursor_sdk import (
        Agent,
        AgentOptions,
        CloudAgentOptions,
        CloudRepository,
        LocalAgentOptions,
    )

    from tempa.qa.config import qa_data_dir

    settings = get_settings()
    api_key = settings.cursor_api_key.strip()
    model = settings.tempa_qa_cursor_model.strip() or "composer-2.5"
    repo = (repo or "").strip()
    local_cwd = (local_cwd or "").strip()

    # Prefer local cwd when set (works in Docker with a mounted checkout).
    # Cloud needs the API key's GitHub connection to see the repo.
    if local_cwd:
        options = AgentOptions(
            api_key=api_key,
            model=model,
            local=LocalAgentOptions(cwd=local_cwd),
        )
    elif repo:
        url = repo if repo.startswith("http") else f"https://github.com/{repo}"
        ref = resolve_cloud_starting_ref(repo, starting_ref)
        options = AgentOptions(
            api_key=api_key,
            model=model,
            cloud=CloudAgentOptions(
                repos=[
                    CloudRepository(
                        url=url,
                        starting_ref=ref,
                    )
                ],
                auto_create_pr=bool(auto_create_pr),
            ),
        )
    else:
        # QA deep-review: prompt carries the diff; scratch cwd is enough.
        scratch = qa_data_dir() / "cursor-scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        options = AgentOptions(
            api_key=api_key,
            model=model,
            local=LocalAgentOptions(cwd=str(scratch)),
        )

    result = Agent.prompt(prompt, options)
    if result.status == "error":
        raise RuntimeError(f"Cursor run failed (run id {result.id})")
    text = str(result.result or "").strip()
    if not text:
        raise RuntimeError("Cursor returned empty response")
    return text


async def cursor_prompt(
    prompt: str,
    *,
    repo: str = "",
    starting_ref: str | None = None,
    local_cwd: str = "",
    auto_create_pr: bool = False,
) -> str:
    """One-shot Cursor run — cloud repo, local cwd, or scratch."""
    if not get_settings().cursor_api_key.strip():
        raise RuntimeError("CURSOR_API_KEY is not set")
    text = await asyncio.to_thread(
        _prompt_sync,
        prompt,
        repo=repo,
        starting_ref=starting_ref,
        local_cwd=local_cwd,
        auto_create_pr=auto_create_pr,
    )
    log.info(
        "cursor.prompt chars=%s repo=%s cwd=%s auto_pr=%s",
        len(text),
        repo or "-",
        local_cwd or "-",
        auto_create_pr,
    )
    return text


async def cursor_complete(*, system: str, user: str, max_tokens: int = 4096) -> str:
    """Run a one-shot Cursor agent review. The diff travels in the prompt; no repo tools needed."""
    # ponytail: max_tokens is accepted for signature parity with claude_complete but the
    # Cursor SDK one-shot API has no token cap parameter; upgrade path is prompt trimming.
    text = await cursor_prompt(f"{system}\n\n{user}")
    log.info("qa.cursor.complete chars=%s", len(text))
    return text
