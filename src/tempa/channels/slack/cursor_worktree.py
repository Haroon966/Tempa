"""Git worktree helpers for isolated Tempa Cursor jobs."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

from tempa.settings import get_settings

log = logging.getLogger(__name__)

_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def _run(cmd: list[str], *, cwd: str | Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=False,
        capture_output=True,
        text=True,
    )


def worktree_root() -> Path:
    settings = get_settings()
    root = settings.tempa_cursor_worktree_root
    if not root.is_absolute():
        root = settings.tempa_data_dir / root
    # Fallback when /repos is unavailable (local dev / tests).
    if str(root).startswith("/repos") and not Path("/repos").exists():
        root = settings.tempa_data_dir / "tempa-worktrees"
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_slug(value: str, *, max_len: int = 40) -> str:
    s = _SAFE.sub("-", (value or "").strip()).strip("-").lower()
    return (s or "x")[:max_len]


def branch_name(*, user_id: str, thread_ts: str, job_id: str) -> str:
    ts = safe_slug(thread_ts.replace(".", ""), max_len=16)
    uid = safe_slug(user_id, max_len=12)
    jid = safe_slug(job_id, max_len=8)
    return f"tempa/{uid}-t{ts}-{jid}"


def ensure_worktree(
    *,
    repo_cwd: str,
    branch: str,
    job_id: str,
    starting_ref: str | None = None,
) -> Path:
    """Create (or reuse) a worktree for this job under the worktree root."""
    repo = Path(repo_cwd)
    if not repo.is_dir():
        raise FileNotFoundError(f"repo cwd missing: {repo_cwd}")
    dest = worktree_root() / safe_slug(repo.name, max_len=32) / safe_slug(job_id, max_len=16)
    if dest.exists():
        return dest

    ref = (starting_ref or "HEAD").strip() or "HEAD"
    # Fetch not required for local HEAD; create branch from ref.
    _run(["git", "fetch", "--all", "--prune"], cwd=repo)
    existing = _run(["git", "rev-parse", "--verify", branch], cwd=repo)
    if existing.returncode == 0:
        proc = _run(["git", "worktree", "add", str(dest), branch], cwd=repo)
    else:
        proc = _run(["git", "worktree", "add", "-b", branch, str(dest), ref], cwd=repo)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "worktree add failed").strip()
        raise RuntimeError(err[:500])
    return dest


def remove_worktree(path: str | Path, *, repo_cwd: str | None = None) -> None:
    dest = Path(path)
    if not dest.exists():
        return
    repo = Path(repo_cwd) if repo_cwd else None
    if repo and repo.is_dir():
        proc = _run(["git", "worktree", "remove", "--force", str(dest)], cwd=repo)
        if proc.returncode != 0:
            log.warning("worktree remove failed: %s", (proc.stderr or "").strip())
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)


def cleanup_orphan_worktrees() -> int:
    """Best-effort: remove empty/orphan dirs under worktree root (boot)."""
    root = worktree_root()
    removed = 0
    if not root.exists():
        return 0
    for child in root.rglob(".git"):
        # skip
        pass
    for path in list(root.glob("*/*")):
        if path.is_dir() and not (path / ".git").exists() and not any(path.iterdir()):
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed


def git_available() -> bool:
    return shutil.which("git") is not None
