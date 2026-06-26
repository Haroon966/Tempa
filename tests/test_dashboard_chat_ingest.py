from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from tempa.api.app import create_app


@pytest.mark.asyncio
async def test_dashboard_chat_ingests_inbound_message():
    app = create_app()
    captured: list[tuple] = []

    def fake_ingest(*args, **kwargs):
        captured.append((args, kwargs))

    async def fake_streaming(message, context, on_token=None):
        return {
            "response": "Two meetings.",
            "sources": [],
            "paused": False,
            "pending_actions": [],
            "artifacts": [],
        }

    with (
        patch("tempa.agents.graph.run_coordinator_streaming", side_effect=fake_streaming),
        patch("tempa.core.chat_sessions.ensure_session") as ensure,
        patch("tempa.core.chat_sessions.append_message"),
        patch("tempa.api.app.ingest_text", side_effect=fake_ingest),
    ):
        ensure.return_value = {"id": "sess-1", "title": "Test", "messages": []}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/chat",
                json={"message": "What's on my calendar tomorrow?", "session_id": "sess-1"},
            )
            assert response.status_code == 200

        await asyncio.sleep(0.05)

    assert captured
    args, kwargs = captured[0]
    assert args[0] == "What's on my calendar tomorrow?"
    assert kwargs["tool"] == "dashboard"
    assert kwargs["source"] == "sess-1"
    assert "inbound" in kwargs["tags"]
