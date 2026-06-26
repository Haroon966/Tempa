"""Branch scan orchestrator."""

from __future__ import annotations

import logging
import shutil
import subprocess
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from tempa.qa.checks.local import parse_pytest_summary, parse_ruff_findings, run_pytest, run_ruff
from tempa.qa.config import load_qa_config, qa_worktrees_dir
from tempa.qa.github.auth import get_github_token, github_uses_pat
from tempa.qa.github.client import gh_get, gh_get_all
from tempa.qa.installations import installation_id_for_repo
from tempa.qa.security.scanner import run_security_scan
from tempa.qa.store import add_finding, compute_grade, upsert_branch_status
from tempa.settings import get_settings

log = logging.getLogger(__name__)


def _repo_slug(repo: str) -> str:
    return repo.replace("/", "__")


def _branch_ignored(branch: str) -> bool:
    patterns = load_qa_config().get("branch_ignore") or []
    return any(fnmatch(branch, str(p)) for p in patterns)


def list_repo_branches(repo: str, token: str, *, max_branches: int | None = None) -> list[dict[str, Any]]:
    limit = max_branches or get_settings().tempa_qa_max_branches_per_repo
    branches = gh_get_all(f"/repos/{repo}/branches?per_page=100", token, max_pages=3)
    result: list[dict[str, Any]] = []
    for b in branches:
        name = str(b.get("name") or "")
        if not name or _branch_ignored(name):
            continue
        result.append(b)
    default = "main"
    try:
        default = str(gh_get(f"/repos/{repo}", token).get("default_branch") or "main")
    except Exception:
        pass
    result.sort(key=lambda x: (0 if x.get("name") == default else 1, str(x.get("name"))))
    return result[:limit]


def get_commit_ci_status(repo: str, sha: str, token: str) -> str:
    try:
        combined = gh_get(f"/repos/{repo}/commits/{sha}/status", token)
        state = str(combined.get("state") or "unknown")
        if state in ("success", "failure", "pending"):
            return state
    except Exception:
        pass
    return "unknown"


def checkout_branch(repo: str, branch: str, token: str) -> tuple[Path | None, str]:
    slug = _repo_slug(repo)
    dest = qa_worktrees_dir() / slug / branch.replace("/", "_")
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    clone_url = f"https://x-access-token:{token}@github.com/{repo}.git"
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", branch, clone_url, str(dest)],
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )
        sha_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=dest,
            check=True,
        )
        return dest, sha_proc.stdout.strip()
    except Exception as exc:
        log.warning("checkout failed %s@%s: %s", repo, branch, exc)
        return None, ""


async def llm_failure_summary(category: str, context: str) -> str:
    try:
        import asyncio

        from tempa.router.groq_router import get_router

        router = get_router()
        prompt = (
            f"Analyze this {category} failure concisely. Return JSON with keys "
            'root_cause (one sentence) and fix (2-4 bullet points).\n\n'
            f"{context[:4000]}"
        )
        messages = [
            {"role": "system", "content": "Senior QA engineer. JSON only."},
            {"role": "user", "content": prompt},
        ]
        response = await asyncio.to_thread(
            router.chat_completion,
            category="reasoning",
            messages=messages,
            max_tokens=512,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:
        log.warning("LLM summary failed: %s", exc)
        return ""


def scan_branch(
    repo: str,
    branch: str,
    *,
    token: str | None = None,
    installation_id: int | None = None,
    scan_job_id: str = "",
) -> dict[str, Any]:
    inst_id = installation_id or installation_id_for_repo(repo)
    if not token:
        try:
            token = get_github_token(repo)
        except RuntimeError as exc:
            raise RuntimeError(f"No GitHub token for repo {repo}") from exc

    cfg = load_qa_config()
    checks = cfg.get("local_checks") or ["ruff", "pytest"]

    try:
        ref = gh_get(f"/repos/{repo}/git/ref/heads/{branch}", token)
        commit_sha = str(ref.get("object", {}).get("sha") or "")
    except Exception:
        commit_sha = ""

    ci_status = get_commit_ci_status(repo, commit_sha, token) if commit_sha else "unknown"
    security_report = run_security_scan(repo, token)
    security_count = security_report.total_count

    lint_status = "skipped"
    test_status = "skipped"
    finding_count = 0

    worktree, checked_sha = checkout_branch(repo, branch, token)
    if checked_sha:
        commit_sha = checked_sha

    if worktree:
        if "ruff" in checks:
            ruff = run_ruff(worktree)
            lint_status = ruff.status
            if ruff.status == "failure":
                for item in parse_ruff_findings(ruff.output)[:20]:
                    add_finding(
                        repo=repo,
                        branch=branch,
                        commit_sha=commit_sha,
                        category="lint_error",
                        severity="medium",
                        title=f"Ruff {item['code']}: {item['message']}",
                        body=ruff.output[:2000],
                        file=str(item["file"]),
                        line=int(item["line"]),
                        scan_job_id=scan_job_id,
                    )
                    finding_count += 1

        if "pytest" in checks:
            pytest_result = run_pytest(worktree)
            test_status = pytest_result.status
            if pytest_result.status == "failure":
                add_finding(
                    repo=repo,
                    branch=branch,
                    commit_sha=commit_sha,
                    category="test_failure",
                    severity="high",
                    title=f"pytest: {parse_pytest_summary(pytest_result.output)}",
                    body=pytest_result.output[:4000],
                    scan_job_id=scan_job_id,
                )
                finding_count += 1

    if ci_status == "failure":
        add_finding(
            repo=repo,
            branch=branch,
            commit_sha=commit_sha,
            category="ci_failure",
            severity="high",
            title=f"CI failing on {branch}",
            body=f"Combined status: {ci_status}",
            scan_job_id=scan_job_id,
        )
        finding_count += 1

    for sf in security_report.all_findings[:15]:
        sev = sf.severity if sf.severity in ("critical", "high", "medium", "low") else "medium"
        add_finding(
            repo=repo,
            branch=branch,
            commit_sha=commit_sha,
            category="vulnerability" if sf.source == "dependabot" else "security",
            severity=sev,
            title=sf.title,
            body=sf.description,
            file=sf.file_path,
            line=sf.line_number,
            scan_job_id=scan_job_id,
        )
        finding_count += 1

    grade = compute_grade(
        ci_status=ci_status,
        lint_status=lint_status,
        test_status=test_status,
        security_count=security_count,
        finding_count=finding_count,
    )
    status = upsert_branch_status(
        repo,
        branch,
        commit_sha=commit_sha,
        ci_status=ci_status,
        lint_status=lint_status,
        test_status=test_status,
        security_count=security_count,
        finding_count=finding_count,
        grade=grade,
    )
    return {
        "repo": repo,
        "branch": branch,
        "commit_sha": commit_sha,
        "grade": grade,
        "finding_count": finding_count,
        "branch_status": status,
    }


def scan_all_branches_for_repo(repo: str, *, installation_id: int | None = None) -> list[str]:
    inst_id = installation_id or installation_id_for_repo(repo)
    if not inst_id and not github_uses_pat():
        return []
    try:
        token = get_github_token(repo)
    except RuntimeError:
        return []
    job_ids: list[str] = []
    from tempa.qa.job_store import enqueue_scan

    for branch_row in list_repo_branches(repo, token):
        branch = str(branch_row.get("name") or "")
        if branch:
            job_ids.append(
                enqueue_scan(repo, branch=branch, installation_id=inst_id, job_type="branch_scan")
            )
    return job_ids
