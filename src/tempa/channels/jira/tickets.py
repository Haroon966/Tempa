from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from tempa.channels.jira.audit import log_ticket_event
from tempa.channels.jira.client import (
    add_comment,
    add_remote_link,
    assign_issue,
    create_issue,
    find_similar_issues,
    jira_enabled,
    update_issue_summary,
)
from tempa.channels.jira.drafts import (
    clear_draft,
    context_key_from_dashboard,
    context_key_from_slack,
    context_key_from_slack_dm,
    has_active_draft,
    load_draft,
    new_draft,
    save_draft,
)
from tempa.channels.jira.intent import (
    TicketFields,
    extract_github_pr_url,
    is_ticket_cancel,
    is_ticket_confirm,
    parse_ticket_request,
    wants_jira_ticket_create,
    wants_jira_ticket_edit,
    wants_jira_ticket_update,
)
from tempa.channels.jira.profiles import remember_jira_email, save_profile
from tempa.channels.jira.sync import ensure_contacts_fresh, ensure_jira_users_fresh
from tempa.channels.jira.users import ResolveResult, resolve_jira_user, validate_account_id
from tempa.settings import get_settings

logger = logging.getLogger(__name__)

_RATE_WINDOW = 3600


def _rate_limit_path() -> Path:
    path = get_settings().sessions_dir / "jira" / "rate_limits.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _check_rate_limit(user_key: str) -> bool:
    limit = get_settings().jira_ticket_rate_limit
    path = _rate_limit_path()
    now = time.time()
    data: dict[str, list[float]] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = {k: [float(t) for t in v] for k, v in raw.items() if isinstance(v, list)}
        except Exception:
            pass
    times = [t for t in data.get(user_key, []) if now - t < _RATE_WINDOW]
    if len(times) >= limit:
        return False
    times.append(now)
    data[user_key] = times
    path.write_text(json.dumps(data), encoding="utf-8")
    return True


def ticket_feature_enabled() -> bool:
    settings = get_settings()
    return settings.jira_ticket_enabled and jira_enabled()


def active_jira_draft(context: dict[str, Any]) -> bool:
    key = _context_key(context)
    return bool(key and has_active_draft(key))


def is_draft_followup(text: str, draft: dict[str, Any] | None) -> bool:
    """True when the user message continues an in-progress ticket draft."""
    if not draft:
        return False
    t = (text or "").strip()
    if not t:
        return False
    # Explicit update of an existing ticket abandons create/gathering drafts.
    if wants_jira_ticket_update(t) and str(draft.get("state") or "") != "created":
        return False
    if is_ticket_confirm(t) or is_ticket_cancel(t) or wants_jira_ticket_edit(t):
        return True

    state = str(draft.get("state") or "")
    if state == "gathering":
        return bool(draft.get("pending_question") or draft.get("ambiguous_options"))
    if state == "created":
        lower = t.lower()
        return any(
            k in lower
            for k in (
                "change assignee",
                "reassign",
                "update summary",
                "edit summary",
                "add comment",
                "add comments",
                "link pr",
                "add reference",
            )
        )
    if state == "preview":
        lower = t.lower()
        if wants_jira_ticket_create(t):
            return True
        # Require clear edit verbs — bare "assign"/"update" in eng chatter must not stick.
        return any(
            k in lower
            for k in (
                "change assignee",
                "reassign",
                "update summary",
                "edit summary",
                "set summary",
                "set assignee",
                "change project",
                "change priority",
                "set priority",
                "set description",
            )
        )
    return state in {"gathering", "confirmed"}


def should_route_to_jira_ticket(text: str, context: dict[str, Any]) -> bool:
    # Cursor-pinned Slack threads never enter Jira create/assignee loops.
    channel_id = str(context.get("slack_channel_id") or "")
    thread_ts = str(context.get("slack_thread_ts") or context.get("thread_ts") or "")
    if channel_id and thread_ts:
        try:
            from tempa.channels.slack.cursor_threads import is_cursor_thread

            if is_cursor_thread(channel_id, thread_ts):
                key = _context_key(context)
                if key:
                    from tempa.channels.jira.drafts import clear_draft

                    clear_draft(key)
                return False
        except Exception:
            pass
    if (
        wants_jira_ticket_create(text)
        or wants_jira_ticket_edit(text)
        or wants_jira_ticket_update(text)
    ):
        return True
    key = _context_key(context)
    if not key or not has_active_draft(key):
        return False
    return is_draft_followup(text, load_draft(key))


def _context_key(context: dict[str, Any]) -> str:
    channel = str(context.get("channel") or "")
    if channel == "slack":
        channel_id = str(context.get("slack_channel_id") or "")
        if context.get("slack_is_dm") or channel_id.startswith("D"):
            if channel_id:
                return context_key_from_slack_dm(channel_id)
        thread_ts = str(context.get("slack_thread_ts") or context.get("thread_ts") or "")
        if channel_id and thread_ts:
            return context_key_from_slack(channel_id, thread_ts)
    session_id = str(context.get("session_id") or context.get("dashboard_session_id") or "")
    if session_id:
        return context_key_from_dashboard(session_id)
    return ""


def _requester_key(context: dict[str, Any]) -> str:
    if context.get("slack_user_id"):
        return f"slack:{context['slack_user_id']}"
    session_id = str(context.get("session_id") or "")
    return f"dashboard:{session_id}" if session_id else "unknown"


def _default_project(context: dict[str, Any]) -> str:
    settings = get_settings()
    slack_id = str(context.get("slack_user_id") or "")
    session_id = str(context.get("session_id") or "")
    from tempa.channels.jira.profiles import get_profile

    profile = get_profile(slack_user_id=slack_id, session_id=session_id)
    if profile and profile.get("default_project"):
        return str(profile["default_project"])
    return settings.jira_default_project or ""


def _fetch_slack_thread(context: dict[str, Any], *, limit: int = 8) -> str:
    if context.get("slack_is_dm"):
        return ""
    channel_id = str(context.get("slack_channel_id") or "")
    thread_ts = str(context.get("slack_thread_ts") or context.get("thread_ts") or "")
    if not channel_id or not thread_ts:
        return ""
    try:
        from tempa.channels.slack.client import iter_thread_replies, list_users, load_slack_client, user_display_name

        client = load_slack_client()
        if client is None:
            return ""
        user_map = {str(u.get("id") or ""): user_display_name(u) for u in list_users(client)}
        lines: list[str] = []
        for msg in iter_thread_replies(client, channel_id, thread_ts, limit=limit):
            uid = str(msg.get("user") or "")
            label = user_map.get(uid, uid or "user")
            text = str(msg.get("text") or "").strip()
            if text:
                lines.append(f"- {label}: {text}")
        return "\n".join(lines)
    except Exception:
        logger.exception("Failed to fetch Slack thread for ticket description")
        return ""


def _context_blob(text: str, context: dict[str, Any], draft: dict[str, Any] | None = None) -> str:
    parts = [text or ""]
    if draft and draft.get("issue_key"):
        parts.append(str(draft.get("issue_key")))
    for msg in context.get("recent_user_messages") or []:
        parts.append(str(msg))
    for turn in context.get("conversation_messages") or []:
        if isinstance(turn, dict):
            parts.append(str(turn.get("text") or ""))
        else:
            parts.append(str(turn))
    thread = _fetch_slack_thread(context, limit=20)
    if thread:
        parts.append(thread)
    return "\n".join(parts)


def resolve_issue_key_from_context(
    text: str,
    context: dict[str, Any],
    draft: dict[str, Any] | None = None,
) -> str:
    from tempa.agents.intent import extract_jira_issue_key

    key = extract_jira_issue_key(text or "")
    if key:
        return key
    if draft and draft.get("issue_key"):
        return str(draft["issue_key"])
    return extract_jira_issue_key(_context_blob(text, context, draft))


def _default_status_comment(text: str, pr_url: str = "") -> str:
    lower = (text or "").lower()
    lines = [
        "Slack update:",
        "- Document completed work vs remaining work on this ticket.",
    ]
    if "comment" in lower or "work that needs" in lower or "what completed" in lower:
        lines.append(
            "- Priority: fix Add Teacher (PEFSIS photo upload) first; Resign is a symptom "
            "until teachers have a real TeacherID."
        )
    if pr_url:
        lines.append(f"- Working PR: {pr_url}")
    else:
        lines.append("- Attach/link the PR where this work will land.")
    return "\n".join(lines)


def try_existing_ticket_update(
    text: str,
    context: dict[str, Any],
    draft: dict[str, Any] | None,
    *,
    context_key: str = "",
) -> str | None:
    """Handle comment/PR-link updates on an existing ticket. Returns reply or None."""
    if not wants_jira_ticket_update(text) and not (
        wants_jira_ticket_edit(text) and ("comment" in text.lower() or "reference" in text.lower())
    ):
        return None

    blob = _context_blob(text, context, draft)
    issue_key = resolve_issue_key_from_context(text, context, draft)
    if not issue_key:
        return (
            "Which Jira issue should I update? Share the key (e.g. MC20-19085) "
            "or link the ticket in this thread."
        )

    # Abandon stale create drafts so we don't keep asking for assignee.
    if context_key and draft and str(draft.get("state") or "") != "created":
        clear_draft(context_key)

    pr_url = extract_github_pr_url(text) or extract_github_pr_url(blob)
    lower = text.lower()
    done: list[str] = []

    wants_comment = any(
        k in lower
        for k in ("comment", "comments", "what completed", "work that needs", "status")
    ) or wants_jira_ticket_update(text)
    if wants_comment:
        # Prefer explicit "add comment <body>" when present; else write a status note.
        body = re.sub(r"(?i)^add\s+comments?\s*", "", text).strip()
        if (
            not body
            or body.lower().startswith("for the work")
            or "use the same ticket" in body.lower()
            or "add reference" in body.lower()
            or len(body) > 500
        ):
            body = _default_status_comment(text, pr_url)
        try:
            add_comment(issue_key, body)
            done.append("comment")
        except Exception as exc:
            logger.exception("Failed to add Jira comment")
            return f"Couldn't add a comment to {issue_key}: {exc}"

    if pr_url or any(k in lower for k in ("reference", "link pr", "pr that")):
        if not pr_url:
            return (
                f"Updated {issue_key} ({', '.join(done) or 'no changes'}) — "
                "share the GitHub PR URL to attach as a reference."
            )
        title = pr_url.rstrip("/").split("/")[-1]
        if title.isdigit():
            title = f"PR #{title}"
        try:
            add_remote_link(issue_key, pr_url, title=title)
            done.append(f"PR link ({pr_url})")
        except Exception as exc:
            logger.exception("Failed to add Jira remote link")
            return f"Comment added to {issue_key}, but linking the PR failed: {exc}"

    if not done:
        return None

    from tempa.channels.jira.session import load_jira_session_config

    base = str(load_jira_session_config().get("base_url") or get_settings().jira_base_url or "").rstrip("/")
    url = f"{base}/browse/{issue_key}" if base else issue_key
    link = f"<{url}|{issue_key}>" if str(url).startswith("http") else issue_key
    return f"Updated *{issue_key}*: {link}\n• " + "\n• ".join(done)


def _format_preview(draft: dict[str, Any]) -> str:
    lines = [
        "*Jira ticket preview*",
        f"Summary: {draft.get('summary') or '(missing)'}",
        f"Assignee: {draft.get('assignee_name') or draft.get('assignee_email') or 'Unassigned'}",
        f"Project: {draft.get('project') or '(default)'}",
    ]
    if draft.get("priority"):
        lines.append(f"Priority: {draft['priority']}")
    if draft.get("description"):
        desc = str(draft["description"])
        if len(desc) > 200:
            desc = desc[:200] + "..."
        lines.append(f"Description: {desc}")
    lines.append("")
    lines.append("Reply *yes* or *go* to create this ticket, or say what to change.")
    return "\n".join(lines)


def _merge_fields(draft: dict[str, Any], fields: TicketFields) -> None:
    if fields.summary and not draft.get("summary"):
        draft["summary"] = fields.summary
    if fields.description:
        draft["description"] = (draft.get("description") or "") + "\n" + fields.description
        draft["description"] = draft["description"].strip()
    if fields.project:
        draft["project"] = fields.project
    if fields.priority:
        draft["priority"] = fields.priority
    if fields.labels:
        draft["labels"] = list(set((draft.get("labels") or []) + fields.labels))
    if fields.self_assign:
        draft["self_assign"] = True
    elif fields.assignee_hint:
        draft["assignee_hint"] = fields.assignee_hint
        draft.pop("self_assign", None)


def _resolve_assignee(draft: dict[str, Any], context: dict[str, Any]) -> str | None:
    """Return clarifying question if unresolved, else None."""
    slack_id = str(context.get("slack_user_id") or "")
    session_id = str(context.get("session_id") or "")

    if draft.get("assignee_account_id"):
        return None

    ambiguous = draft.get("ambiguous_options") or []
    hint = str(draft.get("assignee_hint") or "")
    pick = hint.strip()
    if ambiguous and pick.isdigit():
        idx = int(pick) - 1
        if 0 <= idx < len(ambiguous):
            choice = ambiguous[idx]
            draft["assignee_account_id"] = choice.get("account_id") or ""
            draft["assignee_name"] = choice.get("display_name") or ""
            draft["assignee_email"] = choice.get("email") or ""
            draft["ambiguous_options"] = []
            return None

    self_assign = bool(draft.get("self_assign"))
    # Empty hint with no self-assign → ask who, never "their Jira email" (no person named).
    if not self_assign and not hint.strip():
        draft["pending_question"] = "assignee"
        return "Who should I assign this ticket to? Say a name, email, or 'assign me'."

    # Reject phrase-like "assignees" (e.g. "the work that needs to be done…").
    if not self_assign and (len(hint.split()) > 4 or len(hint) > 48):
        draft["pending_question"] = "assignee"
        draft["assignee_hint"] = ""
        return "Who should I assign this ticket to? Say a name, email, or 'assign me'."

    result = resolve_jira_user(
        hint,
        slack_user_id=slack_id,
        session_id=session_id,
        self_assign=self_assign,
    )

    if result.ambiguous:
        draft["ambiguous_options"] = result.ambiguous[:3]
        names = ", ".join(
            f"{i + 1}. {m.get('display_name') or m.get('email') or m.get('account_id')}"
            for i, m in enumerate(result.ambiguous[:3])
        )
        return f"I found multiple matches for '{hint or 'assignee'}'. Which one?\n{names}\nReply with the number or full name."

    if result.missing and result.needs_input == "jira_email":
        if _EMAIL_RE.match(pick):
            live = resolve_jira_user(pick, slack_user_id=slack_id, session_id=session_id)
            if live.account_id:
                draft["assignee_account_id"] = live.account_id
                draft["assignee_name"] = live.display_name
                draft["assignee_email"] = live.email or pick
                return None
        draft["pending_question"] = "jira_email"
        return "I couldn't find that person in Jira. What is their Jira email address?"

    if result.account_id:
        draft["assignee_account_id"] = result.account_id
        draft["assignee_name"] = result.display_name
        draft["assignee_email"] = result.email
        return None

    return "I couldn't resolve the assignee. Please provide a Jira email or full name."


_EMAIL_RE = re.compile(r"^[\w.\-+]+@[\w.\-]+\.\w+$", re.I)


def _handle_created_followup(draft: dict[str, Any], text: str, context: dict[str, Any]) -> str | None:
    issue_key = str(draft.get("issue_key") or "")
    if not issue_key:
        return None
    lower = text.lower()

    if "change assignee" in lower or "reassign" in lower or "re-assign" in lower:
        m = re.search(r"\bto\s+([A-Za-z][\w.\- ]{1,40})", text, re.I)
        hint = m.group(1).strip() if m else text
        result = resolve_jira_user(hint, slack_user_id=str(context.get("slack_user_id") or ""))
        if result.account_id:
            assign_issue(issue_key, result.account_id)
            return f"Updated {issue_key} — assignee set to {result.display_name or result.account_id}."
        if result.ambiguous:
            return "Multiple matches — please be more specific."
        return "I couldn't find that assignee in Jira."

    if "update summary" in lower or "edit summary" in lower:
        m = re.search(r"(?:summary\s+to|summary:)\s*(.+)", text, re.I)
        new_summary = (m.group(1) if m else text).strip().strip('"')
        if new_summary:
            update_issue_summary(issue_key, new_summary)
            return f"Updated {issue_key} summary."
        return "What should the new summary be?"

    if lower.startswith("add comment") or "add comment" in lower or "add comments" in lower:
        body = re.sub(r"^add\s+comments?\s*", "", text, flags=re.I).strip()
        if body:
            add_comment(issue_key, body)
            return f"Comment added to {issue_key}."
        return "What should the comment say?"

    if any(k in lower for k in ("link pr", "add reference", "reference to the pr")):
        pr_url = extract_github_pr_url(text)
        if not pr_url:
            return "Share the GitHub PR URL to attach."
        add_remote_link(issue_key, pr_url, title=f"PR #{pr_url.rstrip('/').split('/')[-1]}")
        return f"Linked PR on {issue_key}: {pr_url}"

    return None


async def handle_jira_ticket_message(user_message: str, context: dict[str, Any] | None = None) -> str:
    ctx = dict(context or {})
    if not ticket_feature_enabled():
        return "Jira ticket creation is not available — connect Jira in the dashboard first."

    await ensure_jira_users_fresh()
    await ensure_contacts_fresh()

    context_key = _context_key(ctx)
    if not context_key:
        return "I need a conversation thread or session to track this ticket draft."

    requester = _requester_key(ctx)
    draft = load_draft(context_key)
    text = (user_message or "").strip()

    # Existing-ticket updates (comment / PR link) — never fall into create+assignee.
    update_reply = try_existing_ticket_update(text, ctx, draft, context_key=context_key)
    if update_reply is not None:
        return update_reply

    if draft and not is_draft_followup(text, draft) and not wants_jira_ticket_create(text):
        clear_draft(context_key)
        draft = None

    if draft and str(draft.get("state")) == "created":
        followup = _handle_created_followup(draft, text, ctx)
        if followup:
            return followup

    if is_ticket_cancel(text):
        if draft:
            clear_draft(context_key)
        return "Ticket draft cancelled."

    if draft and is_ticket_confirm(text) and draft.get("state") == "preview":
        if not _check_rate_limit(requester):
            return "Rate limit reached — max tickets per hour. Try again later."
        try:
            result = create_issue(
                project=str(draft.get("project") or _default_project(ctx)),
                summary=str(draft.get("summary") or "Untitled"),
                description=str(draft.get("description") or ""),
                assignee_account_id=str(draft.get("assignee_account_id") or ""),
                priority=str(draft.get("priority") or ""),
                labels=list(draft.get("labels") or []),
            )
        except Exception as exc:
            logger.exception("Jira create failed")
            try:
                result = create_issue(
                    project=str(draft.get("project") or _default_project(ctx)),
                    summary=str(draft.get("summary") or "Untitled"),
                    description=str(draft.get("description") or ""),
                )
            except Exception:
                return f"Failed to create Jira ticket: {exc}"

        if result.get("status") != "ok":
            return f"Failed to create ticket: {result.get('reason', 'unknown error')}"

        issue_key = str(result.get("key") or "")
        draft["state"] = "created"
        draft["issue_key"] = issue_key
        save_draft(context_key, draft)

        slack_id = str(ctx.get("slack_user_id") or "")
        session_id = str(ctx.get("session_id") or "")
        if draft.get("assignee_account_id"):
            save_profile(
                slack_user_id=slack_id,
                session_id=session_id,
                jira_account_id=str(draft.get("assignee_account_id") or ""),
                jira_email=str(draft.get("assignee_email") or ""),
                display_name=str(draft.get("assignee_name") or ""),
                default_project=str(draft.get("project") or ""),
                source="ticket_confirm",
            )

        log_ticket_event(
            action="create",
            requester=requester,
            assignee=str(draft.get("assignee_name") or draft.get("assignee_account_id") or ""),
            issue_key=issue_key,
            channel=str(ctx.get("channel") or ""),
        )
        url = result.get("url") or issue_key
        link = f"<{url}|{issue_key}>" if url and str(url).startswith("http") else issue_key
        return (
            f"Created *{issue_key}*: {link}\n"
            f'You can say "change assignee to …", "update summary to …", or "add comment …".'
        )

    # Create only — never treat "add comments / update ticket" as a new draft.
    is_new = wants_jira_ticket_create(text)
    if draft is None and not is_new and not has_active_draft(context_key):
        return ""

    if draft is None:
        draft = new_draft(context_key, channel=str(ctx.get("channel") or "unknown"), requester_id=requester)

    fields = parse_ticket_request(text)
    _merge_fields(draft, fields)

    if draft.get("pending_question") == "jira_email" and _EMAIL_RE.match(text):
        email = text.strip()
        resolved = resolve_jira_user(email, slack_user_id=str(ctx.get("slack_user_id") or ""))
        if resolved.account_id:
            draft["assignee_account_id"] = resolved.account_id
            draft["assignee_name"] = resolved.display_name
            draft["assignee_email"] = email
            draft["pending_question"] = ""
            try:
                from tempa.rag.procedural import add_durable

                name = resolved.display_name or ""
                add_durable(
                    f"{name} email is {email}".strip() if name else f"Email address: {email}",
                    kind="person",
                    source="jira_clarification",
                    tags=["clarification", "jira", "email"],
                )
            except Exception:
                pass
        else:
            remember_jira_email(
                slack_user_id=str(ctx.get("slack_user_id") or ""),
                session_id=str(ctx.get("session_id") or ""),
                email=email,
            )
            draft["assignee_email"] = email
            draft["pending_question"] = ""
            try:
                from tempa.rag.procedural import add_durable

                add_durable(
                    f"Email address: {email}",
                    kind="person",
                    source="jira_clarification",
                    tags=["clarification", "jira", "email"],
                )
            except Exception:
                pass
            return f"I saved {email} but couldn't find a Jira account yet. I'll use it next time — who should I assign this ticket to?"

    if not draft.get("project"):
        draft["project"] = _default_project(ctx)

    thread_ctx = _fetch_slack_thread(ctx)
    if thread_ctx and thread_ctx not in str(draft.get("description") or ""):
        draft["description"] = (draft.get("description") or "") + "\n\nThread context:\n" + thread_ctx
        draft["description"] = draft["description"].strip()

    if not draft.get("summary"):
        draft["pending_question"] = "summary"
        save_draft(context_key, draft)
        return "What should the ticket summary be? A short title describing the work."

    question = _resolve_assignee(draft, ctx)
    if question:
        save_draft(context_key, draft)
        return question

    if not draft.get("project"):
        draft["pending_question"] = "project"
        save_draft(context_key, draft)
        return "Which Jira project key should I use (e.g. ENG)?"

    similar = find_similar_issues(str(draft.get("project") or ""), str(draft.get("summary") or ""))
    draft["state"] = "preview"
    draft["pending_question"] = ""
    save_draft(context_key, draft)

    preview = _format_preview(draft)
    if similar:
        keys = ", ".join(s["key"] for s in similar[:3])
        preview += f"\n\nSimilar existing issues: {keys}"
    return preview
