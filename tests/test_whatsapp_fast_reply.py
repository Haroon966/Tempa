from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tempa.router.groq_router import normalize_groq_messages


def test_normalize_groq_messages_maps_human_to_user():
    out = normalize_groq_messages([{"role": "human", "content": "hi"}])
    assert out == [{"role": "user", "content": "hi"}]


def test_normalize_groq_messages_maps_ai_to_assistant():
    out = normalize_groq_messages([{"role": "ai", "content": "ok"}])
    assert out == [{"role": "assistant", "content": "ok"}]


@pytest.mark.asyncio
async def test_whatsapp_fast_reply(monkeypatch):
    monkeypatch.setenv("WHATSAPP_OWNER_NUMBER", "03435971748")
    from tempa.settings import get_settings

    get_settings.cache_clear()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Hello! How can I help?"))]

    with (
        patch("tempa.channels.whatsapp.reply.is_auto_reply_paused", return_value=False),
        patch("tempa.channels.whatsapp.chat.search_chat_memory", return_value=[]),
        patch("tempa.channels.whatsapp.conversation.get_recent_messages", return_value=[]),
        patch(
            "tempa.channels.whatsapp.chat.get_router",
        ) as get_router,
        patch(
            "tempa.channels.whatsapp.reply.send_whatsapp_message",
            new_callable=AsyncMock,
            return_value={"status": "sent"},
        ) as send,
        patch("tempa.channels.whatsapp.outbound.asyncio.to_thread", side_effect=lambda fn, *a, **k: fn(*a, **k)),
        patch("tempa.channels.whatsapp.outbound.screen_outbound_message", return_value=(True, "ok")),
        patch("tempa.channels.whatsapp.reply.asyncio.create_task"),
        patch("tempa.channels.whatsapp.reply.event_bus.publish_json"),
    ):
        router = MagicMock()
        router.chat_completion.return_value = mock_response
        get_router.return_value = router

        from tempa.channels.whatsapp.reply import handle_inbound_whatsapp

        result = await handle_inbound_whatsapp("923435971748", "Hi", "m1")
        assert result["handled"] == 1
        assert "Hello" in result["reply"]
        router.chat_completion.assert_called_once()
        call_messages = router.chat_completion.call_args.kwargs["messages"]
        assert call_messages[0]["role"] == "system"
        assert call_messages[1]["role"] == "user"
        assert router.chat_completion.call_args.kwargs["category"] == "text"
        send.assert_awaited_once()

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_whatsapp_meet_link_triggers_join(monkeypatch):
    monkeypatch.setenv("WHATSAPP_OWNER_NUMBER", "03435971748")
    from tempa.settings import get_settings

    get_settings.cache_clear()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Joining now."))]

    with (
        patch("tempa.channels.whatsapp.reply.is_auto_reply_paused", return_value=False),
        patch("tempa.channels.whatsapp.chat.search_chat_memory", return_value=[]),
        patch("tempa.channels.whatsapp.conversation.get_recent_messages", return_value=[]),
        patch("tempa.channels.whatsapp.chat.get_router") as get_router,
        patch(
            "tempa.channels.whatsapp.reply.send_whatsapp_message",
            new_callable=AsyncMock,
            return_value={"status": "sent"},
        ),
        patch("tempa.channels.whatsapp.outbound.asyncio.to_thread", side_effect=lambda fn, *a, **k: fn(*a, **k)),
        patch("tempa.channels.whatsapp.outbound.screen_outbound_message", return_value=(True, "ok")),
        patch("tempa.channels.whatsapp.reply.asyncio.create_task"),
        patch("tempa.meet.service.schedule_meeting_join", return_value="meet-job-1") as join,
    ):
        router = MagicMock()
        router.chat_completion.return_value = mock_response
        get_router.return_value = router

        from tempa.channels.whatsapp.reply import handle_inbound_whatsapp

        url = "https://meet.google.com/abc-defg-hij"
        result = await handle_inbound_whatsapp("923435971748", f"join {url}", "m2")
        assert result["handled"] == 1
        join.assert_called_once()
        prompt = router.chat_completion.call_args.kwargs["messages"][1]["content"]
        assert "Conversation thread" in prompt

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_whatsapp_pc_task_uses_coordinator(monkeypatch):
    monkeypatch.setenv("WHATSAPP_OWNER_NUMBER", "03435971748")
    from tempa.settings import get_settings

    get_settings.cache_clear()

    with (
        patch("tempa.channels.whatsapp.reply.is_auto_reply_paused", return_value=False),
        patch(
            "tempa.agents.graph.run_coordinator",
            new_callable=AsyncMock,
            return_value="Opened VS Code for you.",
        ) as coordinator,
        patch(
            "tempa.channels.whatsapp.reply.send_whatsapp_message",
            new_callable=AsyncMock,
            return_value={"status": "sent"},
        ),
        patch("tempa.channels.whatsapp.outbound.asyncio.to_thread", side_effect=lambda fn, *a, **k: fn(*a, **k)),
        patch("tempa.channels.whatsapp.outbound.screen_outbound_message", return_value=(True, "ok")),
        patch("tempa.channels.whatsapp.reply.asyncio.create_task"),
    ):
        from tempa.channels.whatsapp.reply import handle_inbound_whatsapp

        result = await handle_inbound_whatsapp("923435971748", "open vscode please", "m3")
        assert result["handled"] == 1
        assert "VS Code" in result["reply"]
        coordinator.assert_awaited_once()

    get_settings.cache_clear()
