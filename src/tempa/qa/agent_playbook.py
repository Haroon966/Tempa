"""Generate Claude Code / Cursor terminal playbooks with curl commands for Tempa QA."""

from __future__ import annotations

from typing import Any, Literal

from tempa.settings import get_settings

AgentTarget = Literal["claude", "cursor"]


def _api_base() -> str:
    settings = get_settings()
    base = settings.tempa_webhook_base_url.strip()
    if base and "tempa-daemon" not in base:
        return base.rstrip("/")
    port = settings.tempa_daemon_port
    host = settings.tempa_bind_host
    if host in ("0.0.0.0", "::"):
        host = "localhost"
    return f"http://{host}:{port}"


def build_agent_playbook(
    finding: dict[str, Any],
    *,
    target: AgentTarget = "claude",
) -> dict[str, Any]:
    finding_id = str(finding.get("id") or "")
    api = _api_base()
    repo = str(finding.get("repo") or "")
    branch = str(finding.get("branch") or "")
    file_path = str(finding.get("file") or "")
    title = str(finding.get("title") or "QA finding")
    body = str(finding.get("body") or "")[:4000]
    category = str(finding.get("category") or "")
    project_root = str(get_settings().project_root)

    curl_findings = f'curl -s "{api}/api/qa/findings"'
    curl_comment = f'curl -s -X POST "{api}/api/qa/findings/{finding_id}/comment"'
    curl_fix = f'curl -s -X POST "{api}/api/qa/findings/{finding_id}/fix"'
    curl_scan = f'curl -s -X POST "{api}/api/qa/scan" -H "Content-Type: application/json" -d \'{{"repo":"{repo}","branch":"{branch}"}}\''
    curl_summary = f'curl -s "{api}/api/qa/summary"'

    shared_rules = f"""You are a QA engineer fixing a problem reported by Tempa QA Agent.

## Finding
- ID: {finding_id}
- Repo: {repo}
- Branch: {branch}
- Category: {category}
- Title: {title}
- File: {file_path or "(see body)"}

## Details
{body}

## Workflow
1. Inspect and fix the code locally in `{project_root}`.
2. Run: `ruff check src tests` and `pytest -q`
3. Update Tempa using curl (Tempa API base: {api}):
   - Refresh findings: `{curl_findings}`
   - Post GitHub comment after fix: `{curl_comment}`
   - Queue approval-gated autofix PR: `{curl_fix}`
   - Re-scan branch: `{curl_scan}`
   - Check QA summary: `{curl_summary}`
4. Never push directly to main. Use Tempa's approval flow for autofix PRs.
5. After fixing, tell the user what changed and which curl commands you ran."""

    if target == "cursor":
        prompt = f"""{shared_rules}

## Cursor instructions
- Work in the workspace at `{project_root}`.
- Use the Tempa QA API via curl in the integrated terminal to post comments and request fixes.
- Prefer minimal, focused diffs that match existing project style."""
        launch_hint = (
            f"Paste this prompt into Cursor Agent chat (Cmd/Ctrl+L), "
            f"or open Composer and reference `{file_path or 'the failing file'}`."
        )
        terminal_command = None
    else:
        prompt = shared_rules
        launch_hint = (
            f"Run `claude` in `{project_root}`, paste the prompt below, "
            f"and ask Claude to use curl to update Tempa when done."
        )
        terminal_command = f"cd {project_root} && claude"

    return {
        "target": target,
        "finding_id": finding_id,
        "api_base": api,
        "project_root": project_root,
        "prompt": prompt,
        "launch_hint": launch_hint,
        "terminal_command": terminal_command,
        "curl_commands": {
            "list_findings": curl_findings,
            "post_comment": curl_comment,
            "request_fix": curl_fix,
            "scan_branch": curl_scan,
            "summary": curl_summary,
        },
    }
