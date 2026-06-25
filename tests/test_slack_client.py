"""Tests for Slack client conversation listing."""

from unittest.mock import MagicMock

from slack_sdk.errors import SlackApiError

from tempa.channels.slack.client import list_conversations


def _missing_scope_error(needed: str) -> SlackApiError:
    response = MagicMock()
    response.get = lambda key, default=None: {  # noqa: ARG005
        "error": "missing_scope",
        "needed": needed,
    }.get(key, default)
    return SlackApiError(message="missing_scope", response=response)


def test_list_conversations_skips_missing_scope_types():
    client = MagicMock()

    def conversations_list(**kwargs):
        conv_type = kwargs.get("types")
        if conv_type == "private_channel":
            raise _missing_scope_error("groups:read")
        if conv_type == "im":
            return {"channels": [{"id": "D1", "is_im": True}], "response_metadata": {}}
        if conv_type == "public_channel":
            return {"channels": [{"id": "C1", "name": "general"}], "response_metadata": {}}
        return {"channels": [], "response_metadata": {}}

    client.conversations_list.side_effect = conversations_list

    channels = list_conversations(client, types="im,public_channel,private_channel")

    assert len(channels) == 2
    ids = {c["id"] for c in channels}
    assert ids == {"D1", "C1"}
