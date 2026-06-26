"""CI failure handler."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from tempa.qa.config import load_qa_config
from tempa.qa.github.auth import get_github_token, github_uses_pat, get_installation_token
from tempa.qa.github.client import gh_post
from tempa.qa.store import add_finding

log = logging.getLogger(__name__)
SKIP_CONCLUSIONS = {"skipped", "neutral", "cancelled", "success"}


def handle_ci_failure(payload: dict[str, Any]) -> None:
    if payload.get("action") != "completed":
        return
    if not load_qa_config().get("comment_on_ci_failure", True):
        return

    check_run = payload.get("check_run") or {}
    conclusion = str(check_run.get("conclusion") or "")
    if conclusion in SKIP_CONCLUSIONS:
        return

    repo = str((payload.get("repository") or {}).get("full_name") or "")
    check_name = str(check_run.get("name") or "")
    installation_id = int((payload.get("installation") or {}).get("id") or 0)
    if not repo or not installation_id:
        return

    output = check_run.get("output") or {}
    summary = str(output.get("summary") or "")[:2000]
    details = str(output.get("text") or "")[:3000]
    pull_requests = check_run.get("pull_requests") or []
    pr_number = int(pull_requests[0]["number"]) if pull_requests else None

    finding = add_finding(
        repo=repo,
        branch="",
        category="ci_failure",
        severity="high",
        title=f"CI failure: {check_name}",
        body=f"{summary}\n{details}",
        pr_number=pr_number,
    )

    try:
        if github_uses_pat():
            token = get_github_token(repo)
        else:
            token = get_installation_token(installation_id)
    except Exception as exc:
        log.error("CI handler auth failed: %s", exc)
        return

    if pr_number and conclusion == "failure":
        suggestion = _analyze_ci_sync(check_name, summary, details)
        if suggestion:
            from tempa.qa.store import update_finding

            update_finding(finding["id"], suggestion=suggestion)
        comment = _format_ci_comment(check_name, summary, suggestion)
        try:
            resp = gh_post(f"/repos/{repo}/issues/{pr_number}/comments", token, {"body": comment})
            from tempa.qa.store import update_finding

            update_finding(finding["id"], github_comment_url=resp.get("html_url"))
        except Exception as exc:
            log.error("CI comment failed: %s", exc)


def _analyze_ci_sync(check_name: str, summary: str, details: str) -> str:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _analyze_ci_async(check_name, summary, details)).result(
                    timeout=60
                )
        return loop.run_until_complete(_analyze_ci_async(check_name, summary, details))
    except Exception:
        return asyncio.run(_analyze_ci_async(check_name, summary, details))


async def _analyze_ci_async(check_name: str, summary: str, details: str) -> str:
    import asyncio

    from tempa.router.groq_router import get_router

    router = get_router()
    context = f"CI Check: {check_name}\nSummary: {summary}\nDetails: {details}"
    messages = [
        {"role": "system", "content": "DevOps engineer. Return JSON with root_cause and fix fields."},
        {"role": "user", "content": f"Analyze CI failure:\n{context[:3500]}"},
    ]
    try:
        response = await asyncio.to_thread(
            router.chat_completion,
            category="reasoning",
            messages=messages,
            max_tokens=400,
        )
        text = response.choices[0].message.content or ""
        data = json.loads(text.strip().strip("`").removeprefix("json"))
        fix = data.get("fix", "")
        root = data.get("root_cause", "")
        return f"**Root cause:** {root}\n\n**Fix:**\n{fix}"
    except Exception:
        return ""


def _format_ci_comment(check_name: str, summary: str, suggestion: str) -> str:
    body = f"## CI Failure — `{check_name}`\n\n{summary[:1500]}\n"
    if suggestion:
        body += f"\n### Suggested fix\n{suggestion}\n"
    body += "\n---\n*Tempa QA Agent — CI Analysis*"
    return body
