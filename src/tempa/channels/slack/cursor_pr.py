"""GitHub PR helpers for Tempa Cursor jobs (create / adopt / checks / comment)."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from typing import Any

log = logging.getLogger(__name__)

_PR_URL_RE = re.compile(
    r"https?://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/pull/(?P<num>\d+)",
    re.I,
)


def gh_available() -> bool:
    return shutil.which("gh") is not None


def _run(cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)


def parse_pr_url(text: str) -> dict[str, Any] | None:
    m = _PR_URL_RE.search(text or "")
    if not m:
        return None
    return {
        "owner": m.group("owner"),
        "repo": m.group("repo"),
        "full_repo": f"{m.group('owner')}/{m.group('repo')}",
        "pr_number": int(m.group("num")),
        "pr_url": m.group(0).rstrip(").,]"),
    }


def _normalize_pr_state(*, state: str = "", merged: Any = False) -> str:
    """Return OPEN / MERGED / CLOSED from gh pr view fields."""
    if merged is True:
        return "MERGED"
    st = (state or "").strip().upper()
    if st == "MERGED":
        return "MERGED"
    if st in {"CLOSED", "CLOSE"}:
        return "CLOSED"
    if st == "OPEN" or not st:
        return "OPEN"
    return st


def is_pr_open(info: dict[str, Any] | None) -> bool:
    """True only when the PR is still open (not merged/closed)."""
    if not info:
        return False
    if info.get("is_open") is False:
        return False
    if info.get("merged") is True:
        return False
    state = _normalize_pr_state(state=str(info.get("state") or ""), merged=info.get("merged"))
    return state == "OPEN"


def pr_head_ref(pr_number: int, *, cwd: str | None = None, repo: str = "") -> dict[str, Any]:
    """Resolve head branch + lifecycle for an existing PR (adopt / binding)."""
    cmd = ["gh", "pr", "view", str(pr_number), "--json", "headRefName,url,number,state,merged,closedAt"]
    if repo:
        cmd.extend(["--repo", repo])
    proc = _run(cmd, cwd=cwd)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "gh pr view failed").strip()[:400])
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("gh pr view returned invalid JSON") from exc
    head = str(data.get("headRefName") or "").strip()
    if not head:
        raise RuntimeError(f"PR #{pr_number} has no headRefName")
    merged = bool(data.get("merged"))
    state = _normalize_pr_state(state=str(data.get("state") or ""), merged=merged)
    return {
        "branch": head,
        "pr_number": int(data.get("number") or pr_number),
        "pr_url": str(data.get("url") or ""),
        "state": state,
        "merged": merged,
        "closedAt": data.get("closedAt"),
        "is_open": state == "OPEN" and not merged,
    }


def wants_channel_announce(text: str) -> bool:
    t = (text or "").lower()
    return any(
        p in t
        for p in (
            "post in channel",
            "announce in channel",
            "post to channel",
            "share in channel",
            "notify the channel",
        )
    )


def is_write_intent(text: str) -> bool:
    t = (text or "").lower()
    keys = (
        "fix",
        "implement",
        "push",
        "commit",
        "open a pr",
        "open pr",
        "create a pr",
        "create pr",
        "raise a pr",
        "raise pr",
        "rase pr",  # common typo of "raise"
        "make a pr",
        "make pr",
        "ship a pr",
        "pull request",
        "until green",
        "until tests",
        "make the change",
        "apply the",
        "update the code",
        "rewrite",
        "fix it all",
        "fix them all",
        "fix all",
        "qa this",
        "run qa",
        "run tests",
        "failing tests",
        "ci green",
    )
    return any(k in t for k in keys)


def create_pr(
    *,
    cwd: str,
    title: str,
    body: str,
    base: str = "main",
    head: str | None = None,
) -> dict[str, Any]:
    cmd = [
        "gh",
        "pr",
        "create",
        "--title",
        title[:240],
        "--body",
        body[:6000],
        "--base",
        base or "main",
    ]
    if head:
        cmd.extend(["--head", head])
    proc = _run(cmd, cwd=cwd)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "gh pr create failed").strip()[:500])
    url = (proc.stdout or "").strip().splitlines()[-1].strip()
    parsed = parse_pr_url(url) or {}
    return {"pr_url": url, "pr_number": parsed.get("pr_number"), **parsed}


def push_branch(*, cwd: str, branch: str) -> None:
    proc = _run(["git", "push", "-u", "origin", branch], cwd=cwd)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "git push failed").strip()[:500])


def pr_checks(pr_number: int, *, cwd: str | None = None, repo: str = "") -> list[dict[str, Any]]:
    cmd = ["gh", "pr", "checks", str(pr_number), "--json", "name,state,bucket,link"]
    if repo:
        cmd.extend(["--repo", repo])
    proc = _run(cmd, cwd=cwd)
    if proc.returncode != 0:
        # Older gh may not support --json the same way; fall back to text parse.
        text_proc = _run(
            ["gh", "pr", "checks", str(pr_number)] + (["--repo", repo] if repo else []),
            cwd=cwd,
        )
        rows = []
        for line in (text_proc.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                rows.append({"name": parts[0].strip(), "state": parts[1].strip().upper()})
        return rows
    try:
        data = json.loads(proc.stdout or "[]")
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def checks_summary(
    checks: list[dict[str, Any]],
    *,
    required: list[str] | None = None,
) -> dict[str, Any]:
    required = [r.lower() for r in (required or [])]
    pending = False
    failed: list[str] = []
    passed = 0
    for row in checks:
        name = str(row.get("name") or "")
        state = str(row.get("state") or row.get("bucket") or "").upper()
        if required and name.lower() not in required and not any(r in name.lower() for r in required):
            # If required list set, only those names matter (substring match).
            if not any(r in name.lower() for r in required):
                continue
        if state in {"PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED"}:
            pending = True
        elif state in {"FAIL", "FAILURE", "FAILED", "CANCELLED", "TIMED_OUT", "ERROR", "ACTION_REQUIRED"}:
            failed.append(name or state)
        elif state in {"PASS", "SUCCESS"}:
            passed += 1
        # SKIPPED / SKIPPING / NEUTRAL are not passes — leave pending until a real SUCCESS.
    if failed:
        return {"status": "red", "failed": failed, "pending": pending, "passed": passed}
    if pending or (required and passed == 0 and checks):
        return {"status": "pending", "failed": [], "pending": True, "passed": passed}
    if not checks or passed == 0:
        return {"status": "pending", "failed": [], "pending": True, "passed": passed}
    return {"status": "green", "failed": [], "pending": False, "passed": passed}


def pr_comment(*, pr_number: int, body: str, cwd: str | None = None, repo: str = "") -> None:
    cmd = ["gh", "pr", "comment", str(pr_number), "--body", body]
    if repo:
        cmd.extend(["--repo", repo])
    proc = _run(cmd, cwd=cwd)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "gh pr comment failed").strip()[:400])


def fetch_pr_comments(*, pr_number: int, cwd: str | None = None, repo: str = "") -> str:
    cmd = ["gh", "pr", "view", str(pr_number), "--comments", "--json", "comments,reviews,title,url"]
    if repo:
        cmd.extend(["--repo", repo])
    proc = _run(cmd, cwd=cwd)
    if proc.returncode != 0:
        return (proc.stderr or "")[:2000]
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return (proc.stdout or "")[:2000]
    lines: list[str] = []
    for c in data.get("comments") or []:
        if isinstance(c, dict):
            lines.append(f"comment: {(c.get('body') or '')[:400]}")
    for r in data.get("reviews") or []:
        if isinstance(r, dict) and r.get("body"):
            lines.append(f"review: {(r.get('body') or '')[:400]}")
    return "\n".join(lines)[:8000]


def failed_run_logs(*, cwd: str | None = None) -> str:
    proc = _run(["gh", "run", "list", "--limit", "1", "--json", "databaseId,conclusion,url"], cwd=cwd)
    if proc.returncode != 0:
        return ""
    try:
        runs = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return ""
    if not runs:
        return ""
    run_id = runs[0].get("databaseId")
    if not run_id:
        return ""
    logs = _run(["gh", "run", "view", str(run_id), "--log-failed"], cwd=cwd)
    return ((logs.stdout or logs.stderr or "")[:12000])
