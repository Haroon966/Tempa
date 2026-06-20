from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tempa.api.app import create_app


async def _fake_stream():
    for part in ["Hello", " ", "world"]:
        yield part


@pytest.mark.asyncio
async def test_chat_sse_token_and_message_events():
    app = create_app()

    async def fake_streaming(message, context, on_token=None):
        if on_token:
            for part in ["Hi", " there"]:
                await on_token(part)
        return {"response": "Hi there", "sources": [{"label": "rag"}], "paused": False}

    with (
        patch("tempa.agents.graph.run_coordinator_streaming", side_effect=fake_streaming),
        patch("tempa.core.chat_sessions.ensure_session") as ensure,
        patch("tempa.core.chat_sessions.append_message") as append,
    ):
        session = {"id": "sess-1", "title": "Test", "messages": []}
        ensure.return_value = session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream(
                "POST",
                "/api/chat",
                json={"message": "hello", "session_id": "sess-1"},
            ) as response:
                assert response.status_code == 200
                events: list[tuple[str, dict]] = []
                current_event = ""
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        current_event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        data = json.loads(line.split(":", 1)[1].strip())
                        events.append((current_event, data))
                        current_event = ""

        kinds = [e[0] for e in events]
        assert "token" in kinds
        assert "message" in kinds
        assert "done" in kinds
        tokens = "".join(d["delta"] for k, d in events if k == "token")
        assert tokens == "Hi there"
        message = next(d for k, d in events if k == "message")
        assert message["content"] == "Hi there"
        assert message["session_id"] == "sess-1"
        assert append.call_count == 2
