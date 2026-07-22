"""Presence API — #presence channel day board."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/presence")
async def api_presence(date: str | None = Query(default=None, alias="date")):
    from tempa.channels.slack.presence_store import build_payload

    return build_payload(date)


@router.post("/presence/sync")
async def api_presence_sync():
    from tempa.channels.slack.presence_sync import sync_presence_async
    from tempa.channels.slack.presence_store import build_payload

    result = await sync_presence_async()
    payload = build_payload()
    return {"sync": result, "presence": payload}
