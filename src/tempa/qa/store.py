"""Findings and branch status persistence."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from tempa.qa.config import qa_data_dir

_lock = threading.Lock()
Severity = Literal["critical", "high", "medium", "low", "info"]
Category = Literal[
    "test_failure",
    "lint_error",
    "vulnerability",
    "ci_failure",
    "secret",
    "security",
    "other",
]


def _findings_path():
    p = qa_data_dir() / "findings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _branches_path():
    p = qa_data_dir() / "branch_status.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_findings_unlocked() -> dict[str, dict[str, Any]]:
    path = _findings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_findings_unlocked(data: dict[str, dict[str, Any]]) -> None:
    _findings_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_branches_unlocked() -> dict[str, dict[str, Any]]:
    path = _branches_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_branches_unlocked(data: dict[str, dict[str, Any]]) -> None:
    _branches_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _branch_key(repo: str, branch: str) -> str:
    return f"{repo}#{branch}"


def _severity_rank(severity: str) -> int:
    return {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}.get(severity, 0)


def add_finding(
    *,
    repo: str,
    branch: str,
    commit_sha: str = "",
    category: str = "other",
    severity: str = "medium",
    title: str,
    body: str = "",
    suggestion: str = "",
    file: str = "",
    line: int = 0,
    scan_job_id: str = "",
    pr_number: int | None = None,
) -> dict[str, Any]:
    finding_id = str(uuid.uuid4())
    record = {
        "id": finding_id,
        "repo": repo,
        "branch": branch,
        "commit_sha": commit_sha,
        "category": category,
        "severity": severity,
        "title": title,
        "body": body,
        "suggestion": suggestion,
        "file": file,
        "line": line,
        "status": "open",
        "github_comment_url": None,
        "scan_job_id": scan_job_id,
        "pr_number": pr_number,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    with _lock:
        findings = _read_findings_unlocked()
        findings[finding_id] = record
        _write_findings_unlocked(findings)
    return dict(record)


def list_findings(
    *,
    repo: str | None = None,
    branch: str | None = None,
    status: str | None = "open",
    limit: int = 100,
) -> list[dict[str, Any]]:
    with _lock:
        items = list(_read_findings_unlocked().values())
    if repo:
        items = [f for f in items if f.get("repo") == repo]
    if branch:
        items = [f for f in items if f.get("branch") == branch]
    if status:
        items = [f for f in items if f.get("status") == status]
    items.sort(key=lambda f: (_severity_rank(str(f.get("severity"))), f.get("created_at", "")), reverse=True)
    return items[:limit]


def get_finding(finding_id: str) -> dict[str, Any] | None:
    with _lock:
        row = _read_findings_unlocked().get(finding_id)
        return dict(row) if row else None


def update_finding(finding_id: str, **fields: Any) -> dict[str, Any] | None:
    with _lock:
        findings = _read_findings_unlocked()
        row = findings.get(finding_id)
        if not row:
            return None
        row.update(fields)
        row["updated_at"] = _now_iso()
        findings[finding_id] = row
        _write_findings_unlocked(findings)
        return dict(row)


def upsert_branch_status(
    repo: str,
    branch: str,
    *,
    commit_sha: str = "",
    ci_status: str = "unknown",
    lint_status: str = "unknown",
    test_status: str = "unknown",
    security_count: int = 0,
    finding_count: int = 0,
    grade: str = "A",
    last_scan_at: str | None = None,
) -> dict[str, Any]:
    key = _branch_key(repo, branch)
    record = {
        "repo": repo,
        "branch": branch,
        "commit_sha": commit_sha,
        "ci_status": ci_status,
        "lint_status": lint_status,
        "test_status": test_status,
        "security_count": security_count,
        "finding_count": finding_count,
        "grade": grade,
        "last_scan_at": last_scan_at or _now_iso(),
        "updated_at": _now_iso(),
    }
    with _lock:
        branches = _read_branches_unlocked()
        branches[key] = record
        _write_branches_unlocked(branches)
    return dict(record)


def list_branch_statuses(*, repo: str | None = None) -> list[dict[str, Any]]:
    with _lock:
        items = list(_read_branches_unlocked().values())
    if repo:
        items = [b for b in items if b.get("repo") == repo]
    items.sort(key=lambda b: (b.get("repo", ""), b.get("branch", "")))
    return items


def compute_grade(
    *,
    ci_status: str,
    lint_status: str,
    test_status: str,
    security_count: int,
    finding_count: int,
) -> str:
    score = 100
    if ci_status == "failure":
        score -= 25
    elif ci_status == "pending":
        score -= 5
    if lint_status == "failure":
        score -= 20
    if test_status == "failure":
        score -= 25
    score -= min(security_count * 5, 20)
    score -= min(finding_count * 3, 15)
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def summary_stats() -> dict[str, Any]:
    branches = list_branch_statuses()
    findings = list_findings(status="open", limit=10000)
    repos = sorted({b.get("repo") for b in branches if b.get("repo")})
    failing = [b for b in branches if b.get("grade") in ("D", "F") or b.get("ci_status") == "failure"]
    critical = [f for f in findings if f.get("severity") in ("critical", "high")]
    from tempa.qa.job_store import queue_depth

    last_scan = max((b.get("last_scan_at") or "" for b in branches), default="")
    return {
        "repos_monitored": len(repos),
        "branches_scanned": len(branches),
        "failing_branches": len(failing),
        "open_findings": len(findings),
        "critical_findings": len(critical),
        "queue_depth": queue_depth(),
        "last_scan_at": last_scan or None,
    }
