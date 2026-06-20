from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from tempa.core.notifications import recent_notifications
from tempa.core.pending_actions import (
    execute_pending_action,
    get_pending_action,
    list_pending_actions,
    reject_pending_action,
    update_pending_payload,
)
from tempa.core.task_store import list_active_tasks, list_recent_tasks
from tempa.meet.service import get_meeting_jobs

logger = logging.getLogger(__name__)

router = APIRouter()


class PendingActionUpdateRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class ChatSessionCreateRequest(BaseModel):
    title: str = ""


@router.get("/chat/sessions")
async def api_list_chat_sessions():
    from tempa.core.chat_sessions import list_sessions

    return {"sessions": list_sessions()}


@router.post("/chat/sessions")
async def api_create_chat_session(body: ChatSessionCreateRequest | None = None):
    from tempa.core.chat_sessions import create_session

    title = body.title if body else ""
    return create_session(title=title)


@router.get("/chat/sessions/{session_id}")
async def api_get_chat_session(session_id: str):
    from tempa.core.chat_sessions import get_session

    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="not_found")
    return session


@router.delete("/chat/sessions/{session_id}")
async def api_delete_chat_session(session_id: str):
    from tempa.core.chat_sessions import delete_session

    if not delete_session(session_id):
        raise HTTPException(status_code=404, detail="not_found")
    return {"status": "deleted", "id": session_id}


@router.get("/pending-actions")
async def api_list_pending_actions(status: str | None = "pending"):
    return {"actions": list_pending_actions(status=status)}


@router.get("/pending-actions/{action_id}")
async def api_get_pending_action(action_id: str):
    action = get_pending_action(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="not_found")
    return action


@router.post("/pending-actions/{action_id}/approve")
async def api_approve_pending_action(action_id: str):
    result = await execute_pending_action(action_id)
    if result.get("status") == "error" and result.get("reason") == "not_found":
        raise HTTPException(status_code=404, detail="not_found")
    return result


@router.post("/pending-actions/{action_id}/reject")
async def api_reject_pending_action(action_id: str):
    action = reject_pending_action(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="not_found")
    return action


@router.patch("/pending-actions/{action_id}")
async def api_update_pending_action(action_id: str, body: PendingActionUpdateRequest):
    action = update_pending_payload(action_id, body.payload)
    if not action:
        raise HTTPException(status_code=404, detail="not_found or not pending")
    return action


@router.get("/tasks")
async def api_list_tasks():
    meet_jobs = get_meeting_jobs()
    active_meet = [
        {"id": jid, "type": "meet", "status": meta.get("status"), **meta}
        for jid, meta in meet_jobs.items()
        if meta.get("status") in ("queued", "running", "finalizing")
    ]
    return {
        "active": list_active_tasks(),
        "recent": list_recent_tasks(),
        "meet_jobs": active_meet,
    }


@router.get("/notifications")
async def api_notifications(limit: int = 30):
    return {"notifications": recent_notifications(limit)}


@router.get("/gmail/messages")
async def api_gmail_messages(since: str = "", limit: int = 20):
    from tempa.channels.gmail.oauth import load_gmail_client
    from tempa.channels.gmail.sync import load_sync_state

    client = load_gmail_client()
    if client is None:
        return {"status": "disconnected", "messages": []}
    query = "is:unread" if not since else f"after:{since}"
    messages = client.search_message_previews(query, max_results=limit)
    state = load_sync_state()
    return {
        "messages": [
            {
                "id": m.id,
                "subject": m.subject,
                "from": m.sender,
                "date": m.date,
                "snippet": m.snippet,
                "unread": "UNREAD" in (m.label_ids or []),
            }
            for m in messages
        ],
        "last_sync_at": state.get("last_sync_at"),
    }


@router.post("/gmail/sync")
async def api_gmail_sync(full: bool = False):
    from tempa.channels.gmail.sync import sync_once

    return await sync_once(full=full)


@router.get("/contacts")
async def api_contacts(q: str = "", limit: int = 50):
    from tempa.channels.contacts.store import contact_count, list_contacts, search_contacts

    if q.strip():
        return {"contacts": search_contacts(q, limit=limit), "total": await contact_count()}
    return {"contacts": await list_contacts(limit=limit), "total": await contact_count()}


@router.post("/contacts/sync")
async def api_contacts_sync():
    from tempa.channels.contacts.sync import sync_contacts

    return await sync_contacts()


@router.post("/sync/all")
async def api_sync_all(max_emails: int = 500, email_query: str = "newer_than:2y"):
    from tempa.channels.sync_all import sync_all

    return await sync_all(max_emails=max_emails, email_query=email_query)
