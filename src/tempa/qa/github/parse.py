"""Parse GitHub repo, branch, and PR targets from natural language."""

from __future__ import annotations

import re
from dataclasses import dataclass

_REPO_URL_RE = re.compile(r"github\.com/([\w.-]+/[\w.-]+)", re.I)
_PR_URL_RE = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", re.I)
_TREE_URL_RE = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/tree/([^\s?#]+)", re.I)
_SHORT_REPO_RE = re.compile(r"\b([\w.-]+/[\w.-]+)\b")
# "branch develop" / "on branch feature-x"
_BRANCH_AFTER_RE = re.compile(
    r"(?:(?:on|for|scan)\s+)?branch\s+[`'\"]?([^\s`'\",]+)[`'\"]?",
    re.I,
)
# "main branch" / "feature-login branch"
_BRANCH_BEFORE_RE = re.compile(
    r"[`'\"]?([A-Za-z0-9._/\-]+)[`'\"]?\s+branch\b",
    re.I,
)
# "main github.com/owner/repo" — branch named immediately before the URL
_BRANCH_BEFORE_URL_RE = re.compile(
    r"\b([A-Za-z0-9._/\-]+)\s+(?:https?://)?github\.com/",
    re.I,
)
_PR_NUM_RE = re.compile(r"\bpr\s*#?\s*(\d+)\b", re.I)
# Words that look like branch names but aren't when they follow/precede "branch"
_BRANCH_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "any",
        "completly",
        "completely",
        "every",
        "for",
        "fully",
        "here",
        "now",
        "of",
        "on",
        "please",
        "scan",
        "the",
        "this",
        "that",
        "to",
    }
)
_COMMON_BRANCHES = frozenset({"main", "master", "develop", "development", "staging", "release"})

_SCAN_HINTS = ("scan", "check branch", "run qa", "audit", "any fixes", "fix it", "review", "test")
_SCAN_ALL_HINTS = ("scan all", "all repos", "every repo", "all repositories")
_GITHUB_HINTS = ("github.com", "scan repo", "scan this", "pull request", "deep review", "deep-review")
_RESULTS_HINTS = (
    "any error",
    "any bug",
    "any issue",
    "any finding",
    "what did you find",
    "errors found",
    "bugs found",
    "bugs you found",
    "error or bug",
    "errors or bugs",
    "findings",
    "qa result",
    "scan result",
    "review result",
    "what failed",
    "how did the scan",
    "how did the review",
    "status of the scan",
    "status of the qa",
    "report findings",
)


def _clean_branch(name: str | None) -> str | None:
    if not name:
        return None
    cleaned = name.strip().strip("`'\",/")
    if not cleaned or cleaned.lower() in _BRANCH_STOPWORDS:
        return None
    if cleaned.lower() in ("https", "http"):
        return None
    return cleaned


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


def resolve_repo_alias(text: str) -> str:
    """Map product phrases to known repos — 'compliance tracker' → Orenda-Project/compliancetracker."""
    from tempa.qa.installations import list_repos

    compact = re.sub(r"[^a-z0-9]+", "", (text or "").lower())
    if len(compact) < 4:
        return ""
    best = ""
    best_len = 0
    for repo in list_repos():
        name = str(repo or "").strip()
        if name.count("/") != 1:
            continue
        slug = re.sub(r"[^a-z0-9]+", "", name.split("/", 1)[1].lower())
        if len(slug) < 4:
            continue
        if slug in compact and len(slug) > best_len:
            best, best_len = name, len(slug)
    return best


def wants_github_qa(text: str) -> bool:
    lower = (text or "").lower()
    return any(h in lower for h in _GITHUB_HINTS) or any(h in lower for h in _SCAN_HINTS)


def wants_qa_results(text: str) -> bool:
    lower = (text or "").lower()
    if any(h in lower for h in _RESULTS_HINTS):
        return True
    # Short follow-ups like "any bugs?" / "errors?" after a QA request
    return bool(
        re.search(r"\b(error|errors|bug|bugs|issue|issues|finding|findings|result|results)\b", lower)
        and re.search(r"\b(any|found|find|show|list|what|report|tell)\b", lower)
    )


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

    if not target.repo:
        target.repo = resolve_repo_alias(raw)

    if not target.branch:
        # "branch develop" first — avoids treating "owner/repo branch X" as branch=owner/repo
        after = _BRANCH_AFTER_RE.search(raw)
        if after:
            target.branch = _clean_branch(after.group(1))
        if not target.branch:
            before = _BRANCH_BEFORE_RE.search(raw)
            if before:
                target.branch = _clean_branch(before.group(1))
        if not target.branch:
            before_url = _BRANCH_BEFORE_URL_RE.search(raw)
            if before_url:
                candidate = _clean_branch(before_url.group(1))
                if candidate and candidate.lower() in _COMMON_BRANCHES:
                    target.branch = candidate
        if not target.branch:
            # Last resort: a common default branch name appears in the message
            lower = raw.lower()
            for name in ("main", "master", "develop", "staging"):
                if re.search(rf"\b{name}\b", lower):
                    target.branch = name
                    break

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
