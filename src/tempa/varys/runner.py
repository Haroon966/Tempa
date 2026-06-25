from __future__ import annotations

import asyncio
import logging
import os
import shutil
from typing import Any

from tempa.qa.claude import claude_complete, claude_configured
from tempa.settings import get_settings
from tempa.varys.config import load_varys_config

logger = logging.getLogger(__name__)


def claude_cli_available() -> bool:
    settings = get_settings()
    return shutil.which(settings.claude_code_path) is not None


async def _run_claude_cli(
    *,
    system: str,
    user: str,
    cwd: str | None = None,
    timeout: float = 300.0,
) -> str:
    settings = get_settings()
    cmd = [
        settings.claude_code_path,
        "-p",
        "--system-prompt",
        system,
        user,
    ]
    env = dict(os.environ)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd or str(settings.project_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("claude prompt timed out") from None
    if proc.returncode != 0:
        err = (stderr or b"").decode(errors="replace")[:500]
        raise RuntimeError(f"claude exited {proc.returncode}: {err}")
    text = (stdout or b"").decode(errors="replace").strip()
    if not text:
        raise RuntimeError("claude returned empty output")
    return text


async def run_claude_prompt(
    *,
    system: str,
    user: str,
    cwd: str | None = None,
    timeout: float = 300.0,
) -> str:
    settings = get_settings()
    cfg = load_varys_config()
    full_system = system.strip()
    if cfg.agent_name:
        full_system = f"You are {cfg.agent_name}.\n\n{full_system}"

    if claude_cli_available():
        try:
            return await _run_claude_cli(
                system=full_system,
                user=user,
                cwd=cwd,
                timeout=timeout,
            )
        except Exception as exc:
            if settings.varys_claude_cli_only:
                raise RuntimeError(f"Claude Code CLI failed: {exc}") from exc
            logger.warning("Claude CLI failed, trying API fallback: %s", exc)

    if not claude_configured():
        raise RuntimeError(
            "No Claude runner available: install Claude Code CLI or set ANTHROPIC_API_KEY"
        )
    return await claude_complete(system=full_system, user=user)


def run_claude_prompt_sync(
    *,
    system: str,
    user: str,
    cwd: str | None = None,
    timeout: float = 300.0,
) -> str:
    return asyncio.run(
        run_claude_prompt(system=system, user=user, cwd=cwd, timeout=timeout)
    )


async def dispatch_worker(
    *,
    system: str,
    user: str,
    context: dict[str, Any] | None = None,
) -> str:
    _ = context
    return await run_claude_prompt(system=system, user=user)
