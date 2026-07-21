"""QA / CI gate + multi-surface notify for Tempa Cursor jobs."""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from tempa.channels.slack import cursor_pr as cpr
from tempa.settings import get_settings

log = logging.getLogger(__name__)

_JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


def extract_jira_key(text: str, fallback: str | None = None) -> str | None:
    if fallback and str(fallback).strip():
        return str(fallback).strip()
    m = _JIRA_KEY_RE.search(text or "")
    return m.group(1) if m else None


def wants_tests(text: str) -> bool:
    t = (text or "").lower()
    return any(
        p in t
        for p in (
            "run tests",
            "run all tests",
            "run the tests",
            "jest",
            "pytest",
            "until green",
            "ci green",
            "failing tests",
        )
    )


def missing_test_context_message(*, cwd: str, ask_text: str) -> str | None:
    """One-shot Slack ask when tests are requested but known context is absent."""
    import os
    from pathlib import Path

    if not wants_tests(ask_text):
        return None
    env_file = os.environ.get("TEMPA_CURSOR_TEST_ENV_FILE", "").strip()
    if env_file and not Path(env_file).is_file():
        return (
            "_Tempa needs test credentials/context to run everything you asked for. "
            f"Expected `{env_file}` but it is missing — reply with the secrets/path, "
            "or say continue without them. Running what I can meanwhile…_"
        )
    root = Path(cwd) if cwd else None
    if root and root.is_dir():
        # Known CT-style e2e/backend often needs a local .env — ask once if absent.
        if (root / "package.json").exists() and not (root / ".env").exists() and not env_file:
            return (
                "_Tempa can run unit tests, but full coverage usually needs a `.env` "
                "(or `TEMPA_CURSOR_TEST_ENV_FILE`). Reply with credentials/context if you have them — "
                "continuing with what I can run now…_"
            )
    return None


def run_local_tests(cwd: str) -> str:
    """Best-effort local tests when the ask (or known context) wants them."""
    root = Path(cwd)
    if not root.is_dir():
        return ""
    cmds: list[list[str]] = []
    if (root / "package.json").exists():
        cmds.append(["npm", "test", "--", "--passWithNoTests"])
    if (root / "pytest.ini").exists() or (root / "pyproject.toml").exists():
        cmds.append(["pytest", "-q", "--maxfail=5"])
    out_parts: list[str] = []
    for cmd in cmds:
        try:
            proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=600)
        except FileNotFoundError:
            continue
        except Exception as exc:
            out_parts.append(f"{cmd[0]}: {exc}")
            continue
        blob = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        out_parts.append(f"$ {' '.join(cmd)}\nexit={proc.returncode}\n{blob[:4000]}")
        if proc.returncode != 0:
            break
    return "\n\n".join(out_parts)[:8000]


def notify_done(
    *,
    summary: str,
    channel_id: str,
    thread_ts: str,
    ask_text: str,
    pr_number: int | None,
    pr_url: str,
    repo: str,
    cwd: str | None,
    jira_key: str | None,
    user_id: str,
) -> dict[str, Any]:
    """Post done/QA summary to Slack thread (+ channel if asked), GitHub, Jira."""
    from tempa.channels.slack.outbound import send_slack_message_sync

    result: dict[str, Any] = {"slack_thread": False, "slack_channel": False, "github": False, "jira": False}
    body = summary.strip()
    if not body:
        body = f"Tempa finished work on {pr_url or 'the PR'}."

    needs_help = "needs help" in body.lower()
    if needs_help and user_id:
        body = f"<@{user_id}> {body}"

    try:
        send_slack_message_sync(channel_id, body, thread_ts=thread_ts, source_channel="cursor_job")
        result["slack_thread"] = True
    except Exception:
        log.exception("cursor_qa slack thread notify failed")

    if cpr.wants_channel_announce(ask_text):
        try:
            send_slack_message_sync(channel_id, body, thread_ts="", source_channel="cursor_job_channel")
            result["slack_channel"] = True
        except Exception:
            log.exception("cursor_qa channel notify failed")

    if pr_number:
        try:
            gh_body = body
            if needs_help:
                gh_body = (
                    f"Tempa needs help after 3 attempts on this PR.\n\n{summary.strip()[:3500]}"
                )
            cpr.pr_comment(pr_number=pr_number, body=gh_body, cwd=cwd, repo=repo)
            result["github"] = True
        except Exception:
            log.exception("cursor_qa github comment failed")

    ticket = extract_jira_key(ask_text, jira_key)
    if ticket:
        try:
            from tempa.channels.jira.client import add_comment

            add_comment(ticket, body)
            result["jira"] = True
        except Exception:
            log.exception("cursor_qa jira comment failed")

    escalate = get_settings().tempa_cursor_escalate_slack_ids.strip()
    if escalate and needs_help:
        mentions = " ".join(f"<@{uid.strip()}>" for uid in escalate.split(",") if uid.strip())
        if mentions:
            try:
                send_slack_message_sync(
                    channel_id,
                    f"{mentions} — Tempa escalated a Cursor job for <@{user_id}>.\n{body[:500]}",
                    thread_ts=thread_ts,
                    source_channel="cursor_job_escalate",
                )
                result["escalated"] = True
            except Exception:
                log.exception("cursor_qa escalate ping failed")

    return result


def evaluate_ci(
    *,
    pr_number: int,
    cwd: str | None,
    repo: str,
    required_checks: list[str],
) -> dict[str, Any]:
    checks = cpr.pr_checks(pr_number, cwd=cwd, repo=repo)
    return cpr.checks_summary(checks, required=required_checks)


def collect_comment_blockers(*, pr_number: int, cwd: str | None, repo: str) -> str:
    return cpr.fetch_pr_comments(pr_number=pr_number, cwd=cwd, repo=repo)
