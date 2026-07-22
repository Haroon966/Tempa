"""Cursor SDK provider for deep PR reviews and Slack thread answers."""

from __future__ import annotations

import asyncio
import logging

from tempa.settings import get_settings

log = logging.getLogger(__name__)


def cursor_configured() -> bool:
    return bool(get_settings().cursor_api_key.strip())


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
        options = AgentOptions(
            api_key=api_key,
            model=model,
            cloud=CloudAgentOptions(
                repos=[
                    CloudRepository(
                        url=url,
                        starting_ref=starting_ref or None,
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
