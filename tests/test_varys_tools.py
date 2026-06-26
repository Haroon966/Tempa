from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tempa.varys.tools import invoke_runtime_tools


@pytest.mark.asyncio
async def test_invoke_runtime_tools_gmail():
    with patch("tempa.agents.specialists.run_gmail_agent", new_callable=AsyncMock) as mock_gmail:
        mock_gmail.return_value = json_dumps({"status": "ok", "message": "2 unread emails"})
        result = await invoke_runtime_tools("show my unread gmail inbox", {})
    assert "## Gmail" in result
    assert "unread" in result.lower()


@pytest.mark.asyncio
async def test_invoke_runtime_tools_empty_for_generic_chat():
    result = await invoke_runtime_tools("hello there", {})
    assert result == ""


def json_dumps(data):
    import json

    return json.dumps(data)
