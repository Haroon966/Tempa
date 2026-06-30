from __future__ import annotations

import base64
import logging
from datetime import datetime
from typing import Any

import httpx

from tempa.channels.jira.session import load_jira_api_token, load_jira_session_config
from tempa.settings import get_settings

logger = logging.getLogger(__name__)


def jira_configured() -> bool:
    cfg = load_jira_session_config()
    return bool(cfg.get("base_url") and cfg.get("email") and load_jira_api_token())


def _auth_header() -> str:
    cfg = load_jira_session_config()
    token = load_jira_api_token()
    raw = f"{cfg['email']}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _base_url() -> str:
    return load_jira_session_config()["base_url"].rstrip("/")


def jira_request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any] | list[Any] | str]:
    if not jira_configured():
        raise RuntimeError("Jira not configured")
    url = f"{_base_url()}{path}"
    headers = {
        "Authorization": _auth_header(),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.request(method, url, headers=headers, json=json_body, params=params)
    if resp.status_code >= 400:
        detail = resp.text[:500]
        raise RuntimeError(f"Jira API {resp.status_code}: {detail}")
    if not resp.content:
        return resp.status_code, {}
    try:
        return resp.status_code, resp.json()
    except Exception:
        return resp.status_code, resp.text


def test_connection() -> dict[str, Any]:
    _, data = jira_request("GET", "/rest/api/3/myself")
    if not isinstance(data, dict):
        return {"status": "error", "reason": "Unexpected Jira response"}
    return {
        "status": "ok",
        "account_id": data.get("accountId", ""),
        "display_name": data.get("displayName", ""),
        "email": data.get("emailAddress", ""),
    }


def _issue_summary(issue: dict[str, Any]) -> dict[str, Any]:
    fields = issue.get("fields") or {}
    status = fields.get("status") or {}
    assignee = fields.get("assignee") or {}
    project = fields.get("project") or {}
    key = str(issue.get("key") or "")
    base = _base_url()
    return {
        "key": key,
        "summary": str(fields.get("summary") or ""),
        "status": str(status.get("name") or ""),
        "assignee": str(assignee.get("displayName") or assignee.get("emailAddress") or ""),
        "project": str(project.get("key") or ""),
        "updated": str(fields.get("updated") or ""),
        "url": f"{base}/browse/{key}" if key else "",
    }


def search_issues(jql: str, *, max_results: int = 25) -> list[dict[str, Any]]:
    _, data = jira_request(
        "POST",
        "/rest/api/3/search/jql",
        json_body={
            "jql": jql,
            "maxResults": max_results,
            "fields": ["summary", "status", "assignee", "updated", "project"],
        },
    )
    if not isinstance(data, dict):
        return []
    issues = data.get("issues") or []
    return [_issue_summary(issue) for issue in issues if isinstance(issue, dict)]


def get_issue(issue_key: str) -> dict[str, Any]:
    _, data = jira_request(
        "GET",
        f"/rest/api/3/issue/{issue_key}",
        params={"fields": "summary,status,assignee,updated,project,description,issuetype"},
    )
    if not isinstance(data, dict):
        return {"status": "error", "reason": "Invalid issue response"}
    summary = _issue_summary(data)
    fields = data.get("fields") or {}
    desc = fields.get("description")
    summary["description"] = _plain_description(desc)
    summary["issue_type"] = str((fields.get("issuetype") or {}).get("name") or "")
    return summary


def _plain_description(description: Any) -> str:
    if description is None:
        return ""
    if isinstance(description, str):
        return description
    if isinstance(description, dict):
        parts: list[str] = []
        for block in description.get("content") or []:
            if not isinstance(block, dict):
                continue
            for item in block.get("content") or []:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
        return "\n".join(parts).strip()
    return str(description)


def list_projects() -> list[dict[str, Any]]:
    _, data = jira_request("GET", "/rest/api/3/project/search", params={"maxResults": 50})
    if not isinstance(data, dict):
        return []
    values = data.get("values") or []
    return [
        {
            "key": str(p.get("key") or ""),
            "name": str(p.get("name") or ""),
            "id": str(p.get("id") or ""),
        }
        for p in values
        if isinstance(p, dict)
    ]


def since_iso_to_jql_datetime(since_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return "1970-01-01 00:00"


def build_updated_jql(projects: list[str], since_iso: str) -> str:
    since = since_iso_to_jql_datetime(since_iso)
    if projects:
        keys = ", ".join(projects)
        return f'project in ({keys}) AND updated >= "{since}" ORDER BY updated ASC'
    return f'updated >= "{since}" ORDER BY updated ASC'


def poll_updated_issues(projects: list[str], since_iso: str) -> list[dict[str, Any]]:
    jql = build_updated_jql(projects, since_iso)
    return search_issues(jql, max_results=50)


def _user_summary(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "account_id": str(user.get("accountId") or ""),
        "display_name": str(user.get("displayName") or ""),
        "email": str(user.get("emailAddress") or ""),
        "active": bool(user.get("active", True)),
    }


def search_users(query: str, *, max_results: int = 10) -> list[dict[str, Any]]:
    _, data = jira_request(
        "GET",
        "/rest/api/3/user/search",
        params={"query": query.strip(), "maxResults": max_results},
    )
    if not isinstance(data, list):
        return []
    return [_user_summary(u) for u in data if isinstance(u, dict) and u.get("accountId")]


def list_assignable_users(project_key: str, *, max_results: int = 100) -> list[dict[str, Any]]:
    _, data = jira_request(
        "GET",
        "/rest/api/3/user/assignable/search",
        params={"project": project_key, "maxResults": max_results},
    )
    if not isinstance(data, list):
        return []
    return [_user_summary(u) for u in data if isinstance(u, dict) and u.get("accountId")]


def get_user_by_account_id(account_id: str) -> dict[str, Any] | None:
    if not account_id.strip():
        return None
    try:
        _, data = jira_request("GET", f"/rest/api/3/user", params={"accountId": account_id.strip()})
    except RuntimeError:
        return None
    if not isinstance(data, dict):
        return None
    return _user_summary(data)


def _adf_paragraph(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text.strip()}],
            }
        ],
    }


def find_similar_issues(project: str, summary: str, *, max_results: int = 5) -> list[dict[str, Any]]:
    words = [w for w in summary.split() if len(w) > 3][:4]
    if not words:
        return []
    term = " ".join(words).replace('"', "")
    jql = f'project = {project} AND summary ~ "{term}" ORDER BY updated DESC'
    try:
        return search_issues(jql, max_results=max_results)
    except RuntimeError:
        return []


def create_issue(
    *,
    project: str,
    summary: str,
    description: str = "",
    issue_type: str = "Task",
    assignee_account_id: str = "",
    reporter_account_id: str = "",
    priority: str = "",
    labels: list[str] | None = None,
    components: list[str] | None = None,
) -> dict[str, Any]:
    project_key = project.strip() or load_jira_session_config().get("default_project", "")
    if not project_key:
        raise ValueError("Jira project key required")
    fields: dict[str, Any] = {
        "project": {"key": project_key},
        "summary": summary,
        "issuetype": {"name": issue_type},
    }
    if description.strip():
        fields["description"] = _adf_paragraph(description)
    if assignee_account_id.strip():
        fields["assignee"] = {"id": assignee_account_id.strip()}
    if reporter_account_id.strip():
        fields["reporter"] = {"id": reporter_account_id.strip()}
    if priority.strip():
        fields["priority"] = {"name": priority.strip()}
    if labels:
        fields["labels"] = [label for label in labels if label]
    if components:
        fields["components"] = [{"name": c} for c in components if c]
    _, data = jira_request("POST", "/rest/api/3/issue", json_body={"fields": fields})
    if not isinstance(data, dict):
        return {"status": "error", "reason": "Unexpected create response"}
    key = str(data.get("key") or "")
    return {
        "status": "ok",
        "key": key,
        "id": str(data.get("id") or ""),
        "url": f"{_base_url()}/browse/{key}" if key else "",
    }


def update_issue(issue_key: str, fields: dict[str, Any]) -> dict[str, Any]:
    jira_request("PUT", f"/rest/api/3/issue/{issue_key}", json_body={"fields": fields})
    return {"status": "ok", "issue_key": issue_key}


def assign_issue(issue_key: str, account_id: str) -> dict[str, Any]:
    return update_issue(issue_key, {"assignee": {"id": account_id.strip()}})


def update_issue_summary(issue_key: str, summary: str) -> dict[str, Any]:
    return update_issue(issue_key, {"summary": summary.strip()})


def add_comment(issue_key: str, body: str) -> dict[str, Any]:
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": body.strip()}],
                }
            ],
        }
    }
    _, data = jira_request("POST", f"/rest/api/3/issue/{issue_key}/comment", json_body=payload)
    if not isinstance(data, dict):
        return {"status": "error", "reason": "Unexpected comment response"}
    return {"status": "ok", "comment_id": str(data.get("id") or ""), "issue_key": issue_key}


def transition_issue(issue_key: str, transition_name: str) -> dict[str, Any]:
    _, transitions_data = jira_request("GET", f"/rest/api/3/issue/{issue_key}/transitions")
    if not isinstance(transitions_data, dict):
        return {"status": "error", "reason": "Could not load transitions"}
    transition_id = None
    for tr in transitions_data.get("transitions") or []:
        if not isinstance(tr, dict):
            continue
        name = str(tr.get("name") or "")
        if name.lower() == transition_name.strip().lower():
            transition_id = tr.get("id")
            break
    if transition_id is None:
        available = [
            str(tr.get("name") or "")
            for tr in (transitions_data.get("transitions") or [])
            if isinstance(tr, dict)
        ]
        return {
            "status": "error",
            "reason": f"Transition '{transition_name}' not found",
            "available": available,
        }
    jira_request(
        "POST",
        f"/rest/api/3/issue/{issue_key}/transitions",
        json_body={"transition": {"id": transition_id}},
    )
    return {"status": "ok", "issue_key": issue_key, "transition": transition_name}


def jira_enabled() -> bool:
    settings = get_settings()
    if not settings.jira_enabled:
        from tempa.varys.config import load_varys_config

        if not load_varys_config().jira_enabled:
            return False
    return jira_configured()
