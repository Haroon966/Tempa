"""Git worktree helpers for isolated Tempa Cursor jobs."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from tempa.settings import get_settings

log = logging.getLogger(__name__)

_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")
_GIT_SAFE_READY = False


def ensure_git_safe_directories(*paths: str | Path) -> None:
    """Allow git on host-mounted repos (Docker often runs as root; checkout is uid 1000).

    Also exports GIT_CONFIG_* so Cursor Agent / child processes inherit the same policy.
    """
    global _GIT_SAFE_READY
    targets: list[str] = ["*"]
    for path in paths:
        p = Path(path).resolve() if path else None
        if p and p.exists():
            targets.append(str(p))
            # Parent /repos so worktrees under /repos/tempa-worktrees are covered too.
            if p.parent.name and str(p.parent) not in targets:
                targets.append(str(p.parent))
    # Deduplicate, keep order.
    seen: set[str] = set()
    uniq = [t for t in targets if not (t in seen or seen.add(t))]
    for directory in uniq:
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", directory],
            check=False,
            capture_output=True,
            text=True,
        )
    # Cursor Agent spawns its own git; env beats global config when the agent
    # runs with a different HOME.
    os.environ.setdefault("GIT_CONFIG_COUNT", "1")
    os.environ.setdefault("GIT_CONFIG_KEY_0", "safe.directory")
    os.environ.setdefault("GIT_CONFIG_VALUE_0", "*")
    _GIT_SAFE_READY = True


def _run(cmd: list[str], *, cwd: str | Path | None = None) -> subprocess.CompletedProcess[str]:
    if not _GIT_SAFE_READY:
        ensure_git_safe_directories(cwd or "", "/repos")
    # -c safe.directory=* covers this invocation even if global config was skipped.
    git_cmd = cmd
    if cmd and cmd[0] == "git" and "-c" not in cmd[:3]:
        git_cmd = ["git", "-c", "safe.directory=*", *cmd[1:]]
    return subprocess.run(
        git_cmd,
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


def ensure_repo_mirror(repo: str, *, ref: str = "main") -> Path:
    """Shallow clone (or update) an unmounted GitHub repo for local Cursor + gh PR.

    Used when Cursor cloud cannot see the repo but Tempa's GitHub token can clone.
    """
    slug = (repo or "").strip().replace("https://github.com/", "").strip("/")
    if slug.count("/") != 1:
        raise ValueError(f"invalid github repo slug: {repo!r}")
    branch = (ref or "main").strip() or "main"
    dest = worktree_root() / "mirrors" / safe_slug(slug.replace("/", "__"), max_len=64)
    dest.parent.mkdir(parents=True, exist_ok=True)
    ensure_git_safe_directories(dest, dest.parent, "/repos")

    token = ""
    try:
        from tempa.qa.github.auth import get_github_token

        token = (get_github_token(slug) or "").strip()
    except Exception:
        token = ""
    if token:
        clone_url = f"https://x-access-token:{token}@github.com/{slug}.git"
    else:
        clone_url = f"https://github.com/{slug}.git"

    if (dest / ".git").exists():
        # Refresh mirror to the requested branch tip.
        _run(["git", "remote", "set-url", "origin", clone_url], cwd=dest)
        fetch = _run(["git", "fetch", "--depth", "1", "origin", branch], cwd=dest)
        if fetch.returncode != 0:
            raise RuntimeError((fetch.stderr or fetch.stdout or "git fetch failed").strip()[:400])
        checkout = _run(["git", "checkout", "-B", branch, f"origin/{branch}"], cwd=dest)
        if checkout.returncode != 0:
            raise RuntimeError((checkout.stderr or checkout.stdout or "git checkout failed").strip()[:400])
        return dest

    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    proc = _run(
        ["git", "clone", "--depth", "1", "--branch", branch, clone_url, str(dest)],
        cwd=dest.parent,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "git clone failed").strip()[:400])
    # Avoid leaking the token into later `git remote -v` logs for child agents.
    _run(["git", "remote", "set-url", "origin", f"https://github.com/{slug}.git"], cwd=dest)
    if token:
        # Keep authenticated push URL in a helper remote for Tempa push/create_pr.
        _run(["git", "remote", "set-url", "origin", clone_url], cwd=dest)
    return dest
