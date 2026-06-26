"""Parse GitHub repo, branch, and PR targets from natural language."""

from __future__ import annotations

import re
from dataclasses import dataclass

_REPO_URL_RE = re.compile(r"github\.com/([\w.-]+/[\w.-]+)", re.I)
_PR_URL_RE = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", re.I)
_TREE_URL_RE = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/tree/([^\s?#]+)", re.I)
_SHORT_REPO_RE = re.compile(r"\b([\w.-]+/[\w.-]+)\b")
_BRANCH_RE = re.compile(
    r"(?:branch|on\s+branch|for\s+branch|scan\s+branch)\s+[`'\"]?([^\s`'\",]+)[`'\"]?",
    re.I,
)
_PR_NUM_RE = re.compile(r"\bpr\s*#?\s*(\d+)\b", re.I)

_SCAN_HINTS = ("scan", "check branch", "run qa", "audit", "any fixes", "fix it", "review")
_SCAN_ALL_HINTS = ("scan all", "all repos", "every repo", "all repositories")
_GITHUB_HINTS = ("github.com", "scan repo", "scan this", "pull request", "deep review", "deep-review")


@dataclass
class GitHubTarget:
    repo: str = ""
    branch: str | None = None
    pr_number: int | None = None


def normalize_repo_name(repo: str) -> str:
    from tempa.qa.allowed_repos import normalize_repo

    name = normalize_repo(repo)
    if not name or "github.com" in name.lower():
        return ""
    return name


def wants_github_qa(text: str) -> bool:
    lower = (text or "").lower()
    return any(h in lower for h in _GITHUB_HINTS) or any(h in lower for h in _SCAN_HINTS)


def wants_scan_all(text: str) -> bool:
    lower = (text or "").lower()
    return any(h in lower for h in _SCAN_ALL_HINTS)


def parse_github_target(text: str) -> GitHubTarget:
    raw = text or ""
    target = GitHubTarget()

    pr_match = _PR_URL_RE.search(raw)
    if pr_match:
        target.repo = normalize_repo_name(pr_match.group(1))
        target.pr_number = int(pr_match.group(2))
        return target

    tree_match = _TREE_URL_RE.search(raw)
    if tree_match:
        target.repo = normalize_repo_name(tree_match.group(1))
        branch = tree_match.group(2).strip("/")
        target.branch = branch or None
        return target

    repo_match = _REPO_URL_RE.search(raw)
    if repo_match:
        target.repo = normalize_repo_name(repo_match.group(1))

    if not target.repo:
        for match in _SHORT_REPO_RE.finditer(raw):
            candidate = normalize_repo_name(match.group(1))
            if candidate and candidate.count("/") == 1:
                target.repo = candidate
                break

    branch_match = _BRANCH_RE.search(raw)
    if branch_match and not target.branch:
        target.branch = branch_match.group(1).strip("/") or None

    if target.pr_number is None:
        pr_num_match = _PR_NUM_RE.search(raw)
        if pr_num_match:
            target.pr_number = int(pr_num_match.group(1))

    return target


def parse_pr_from_text(text: str) -> tuple[str, int] | None:
    target = parse_github_target(text)
    if target.repo and target.pr_number:
        return target.repo, target.pr_number
    pr_num_match = _PR_NUM_RE.search(text or "")
    if pr_num_match:
        return "", int(pr_num_match.group(1))
    return None
