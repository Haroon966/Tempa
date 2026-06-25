"""Approval-gated autofix via GitHub PR."""

from __future__ import annotations

import base64
import logging
import re
from typing import Any

from tempa.qa.github.client import gh_get, gh_post, GitHubError

log = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".py", ".md", ".txt", ".yml", ".yaml", ".json", ".toml"}
BLOCKED_PATHS = {
    ".env",
    "Dockerfile",
    "docker-compose.yml",
    "pyproject.toml",
    ".github/workflows/ci.yml",
}
BLOCKED_PREFIXES = (".github/workflows/", ".env", "secrets/", "certs/")


def _is_allowed(path: str) -> bool:
    if not path or ".." in path or path.startswith("/"):
        return False
    if path in BLOCKED_PATHS:
        return False
    if any(path.startswith(p) for p in BLOCKED_PREFIXES):
        return False
    ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
    return ext in ALLOWED_EXTENSIONS or path.endswith("requirements.txt")


def _default_branch(repo: str, token: str) -> str:
    try:
        return str(gh_get(f"/repos/{repo}", token).get("default_branch") or "main")
    except Exception:
        return "main"


def _create_branch(repo: str, token: str, branch: str, base: str) -> None:
    ref = gh_get(f"/repos/{repo}/git/ref/heads/{base}", token)
    sha = ref["object"]["sha"]
    gh_post(f"/repos/{repo}/git/refs", token, {"ref": f"refs/heads/{branch}", "sha": sha})


def _read_file(repo: str, path: str, ref: str, token: str) -> str:
    data = gh_get(f"/repos/{repo}/contents/{path}?ref={ref}", token)
    return base64.b64decode(data["content"]).decode("utf-8")


def _commit_file(repo: str, path: str, content: str, branch: str, message: str, token: str) -> None:
    existing_sha = None
    try:
        data = gh_get(f"/repos/{repo}/contents/{path}?ref={branch}", token)
        existing_sha = data.get("sha")
    except GitHubError:
        pass
    payload: dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if existing_sha:
        payload["sha"] = existing_sha
    gh_post(f"/repos/{repo}/contents/{path}", token, payload)


def apply_autofix(payload: dict[str, Any]) -> dict[str, Any]:
    repo = str(payload.get("repo") or "")
    branch = str(payload.get("branch") or "")
    file_path = str(payload.get("file") or "")
    patch_content = str(payload.get("patch_content") or payload.get("content") or "")
    finding_id = str(payload.get("finding_id") or "")
    token = str(payload.get("token") or "")

    if not all([repo, file_path, patch_content, token]):
        raise ValueError("Missing autofix payload fields")

    if not _is_allowed(file_path):
        raise ValueError(f"Autofix blocked for path: {file_path}")

    fix_branch = f"tempa-qa/fix-{finding_id[:8] or 'patch'}"
    base = branch or _default_branch(repo, token)
    _create_branch(repo, token, fix_branch, base)
    _commit_file(
        repo,
        file_path,
        patch_content,
        fix_branch,
        f"fix(qa): {payload.get('title', 'automated fix')[:72]}",
        token,
    )
    pr = gh_post(
        f"/repos/{repo}/pulls",
        token,
        {
            "title": f"QA fix: {payload.get('title', file_path)[:80]}",
            "head": fix_branch,
            "base": base,
            "body": (
                f"Automated fix from Tempa QA (finding `{finding_id}`).\n\n"
                f"**File:** `{file_path}`\n\n"
                "Please review before merging."
            ),
        },
    )
    return {"status": "pr_created", "pr_url": pr.get("html_url"), "branch": fix_branch}


async def generate_fix_patch(finding: dict[str, Any]) -> dict[str, Any]:
    import asyncio

    from tempa.router.groq_router import get_router

    router = get_router()
    file_path = str(finding.get("file") or "")
    prompt = (
        f"Given this QA finding, return the full corrected file content for `{file_path}`.\n"
        f"Title: {finding.get('title')}\n"
        f"Body:\n{finding.get('body', '')[:3000]}\n"
        "Return only the file content, no markdown fences."
    )
    messages = [
        {"role": "system", "content": "Expert software engineer. Output only valid file content."},
        {"role": "user", "content": prompt},
    ]
    response = await asyncio.to_thread(
        router.chat_completion,
        category="reasoning",
        messages=messages,
        max_tokens=4096,
    )
    content = response.choices[0].message.content or ""
    content = re.sub(r"^```[\w]*\n?", "", content.strip())
    content = re.sub(r"\n?```$", "", content)
    return {"file": file_path, "patch_content": content, "repo": finding.get("repo"), "branch": finding.get("branch")}
