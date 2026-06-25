"""Local lint and test runners."""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from tempa.qa.config import load_qa_config

log = logging.getLogger(__name__)


@dataclass
class CheckResult:
    name: str
    status: str  # success | failure | skipped
    output: str = ""
    exit_code: int = 0


def run_ruff(worktree: Path) -> CheckResult:
    cfg = load_qa_config()
    paths = cfg.get("ruff_paths") or ["src", "tests"]
    args = ["ruff", "check", *[str(worktree / p) for p in paths if (worktree / p).exists()]]
    if len(args) <= 2:
        return CheckResult(name="ruff", status="skipped", output="No ruff paths found")
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=120, cwd=worktree)
        status = "success" if proc.returncode == 0 else "failure"
        output = (proc.stdout or "") + (proc.stderr or "")
        return CheckResult(name="ruff", status=status, output=output[:8000], exit_code=proc.returncode or 0)
    except FileNotFoundError:
        return CheckResult(name="ruff", status="skipped", output="ruff not installed")
    except subprocess.TimeoutExpired:
        return CheckResult(name="ruff", status="failure", output="ruff timed out", exit_code=1)


def run_pytest(worktree: Path) -> CheckResult:
    cfg = load_qa_config()
    timeout = int(cfg.get("pytest_timeout_seconds") or 600)
    if not (worktree / "tests").exists() and not list(worktree.glob("test_*.py")):
        return CheckResult(name="pytest", status="skipped", output="No tests directory")
    try:
        proc = subprocess.run(
            ["pytest", "-q", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=worktree,
        )
        status = "success" if proc.returncode == 0 else "failure"
        output = (proc.stdout or "") + (proc.stderr or "")
        return CheckResult(name="pytest", status=status, output=output[:12000], exit_code=proc.returncode or 0)
    except FileNotFoundError:
        return CheckResult(name="pytest", status="skipped", output="pytest not installed")
    except subprocess.TimeoutExpired:
        return CheckResult(name="pytest", status="failure", output="pytest timed out", exit_code=1)


def parse_ruff_findings(output: str) -> list[dict[str, str | int]]:
    findings: list[dict[str, str | int]] = []
    for line in output.splitlines():
        m = re.match(r"^(.+?):(\d+):\d+:\s+(\S+)\s+(.+)$", line.strip())
        if m:
            findings.append({"file": m.group(1), "line": int(m.group(2)), "code": m.group(3), "message": m.group(4)})
    return findings


def parse_pytest_summary(output: str) -> str:
    for line in reversed(output.splitlines()):
        if "failed" in line or "error" in line or "passed" in line:
            return line.strip()
    return output.strip()[:500]
