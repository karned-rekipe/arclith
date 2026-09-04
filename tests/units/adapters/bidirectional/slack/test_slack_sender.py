from __future__ import annotations

import json

import httpx
import pytest

import arclith.adapters.bidirectional.slack.sender as slack_sender
from arclith.adapters.bidirectional.slack import SlackChannelSender
from arclith.domain.errors.channel import (
    ChannelDeliveryFailed,
    ChannelRateLimited,
    ChannelUnauthorized,
    ChannelUnavailable,
)
from arclith.domain.models.channel import ChannelAttachment, ChannelOutgoingMessage
from arclith.infrastructure.settings.channel import SlackChannelSettings


def _settings() -> SlackChannelSettings:
    return SlackChannelSettings(
        signing_secret="1234567890abcdef1234567890abcdef",
        bot_token="xoxb-secret-token",
    )


def _message(**overrides: object) -> ChannelOutgoingMessage:
    return ChannelOutgoingMessage.model_validate(
        {
            "message_id": "msg-1",
            "channel": "slack",
            "conversation_id": "C123ABC456",
            "thread_id": "1700000000.000100",
            "text": "pong",
            **overrides,
        }
    )


async def test_sender_posts_text_to_exact_slack_thread() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://slack.com/api/chat.postMessage"
        assert request.headers["Authorization"] == "Bearer xoxb-secret-token"
        assert json.loads(request.content) == {
            "channel": "C123ABC456",
            "text": "pong",
            "client_msg_id": "msg-1",
            "thread_ts": "1700000000.000100",
        }
        return httpx.Response(
            200,
            json={"ok": True, "channel": "C123ABC456", "ts": "1700000001.2"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await SlackChannelSender(_settings(), client=client).send(_message())

    assert receipt.status == "delivered"
    assert receipt.provider_message_id == "1700000001.2"
    assert receipt.metadata == {"channel_id": "C123ABC456"}


@pytest.mark.parametrize(
    ("status_code", "payload", "error_type"),
    [
        (400, {"ok": False, "error": "bad_request"}, ChannelDeliveryFailed),
        (500, {"ok": False, "error": "fatal_error"}, ChannelUnavailable),
        (200, {"ok": False, "error": "invalid_auth"}, ChannelUnauthorized),
        (200, {"ok": False, "error": "internal_error"}, ChannelUnavailable),
        (200, {"ok": True, "channel": "C123ABC456"}, ChannelDeliveryFailed),
    ],
)
async def test_sender_maps_provider_failures_without_response_details(
    status_code: int,
    payload: dict[str, object],
    error_type: type[Exception],
) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(status_code, json=payload)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(error_type) as captured:
            await SlackChannelSender(_settings(), client=client).send(_message())

    assert "bad_request" not in str(captured.value)
    assert "xoxb-secret-token" not in str(captured.value)


@pytest.mark.parametrize(
    ("status_code", "payload"),
    [
        (429, {"ok": False, "error": "ratelimited"}),
        (200, {"ok": False, "error": "rate_limited"}),
    ],
)
async def test_sender_exposes_numeric_retry_after_only(
    status_code: int,
    payload: dict[str, object],
) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            status_code,
            json=payload,
            headers={"Retry-After": "2.5"},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ChannelRateLimited) as captured:
            await SlackChannelSender(_settings(), client=client).send(_message())

    assert captured.value.retry_after_seconds == 2.5


async def test_sender_maps_transport_timeouts_and_invalid_json() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider secret timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(ChannelUnavailable) as captured:
            await SlackChannelSender(_settings(), client=client).send(_message())
    assert "provider secret timeout" not in str(captured.value)

    invalid = httpx.MockTransport(lambda _request: httpx.Response(200, text="secret"))
    async with httpx.AsyncClient(transport=invalid) as client:
        with pytest.raises(ChannelDeliveryFailed, match="invalid response"):
            await SlackChannelSender(_settings(), client=client).send(_message())


async def test_sender_rejects_unsupported_outgoing_messages() -> None:
    wrong_channel = _message(channel="webhook")
    attachment = ChannelAttachment(
        kind="file",
        storage_key="messages/file.txt",
    )
    attachment_only = _message(text=None, attachments=[attachment])

    with pytest.raises(ChannelDeliveryFailed, match="slack channel"):
        await SlackChannelSender(_settings()).send(wrong_channel)
    with pytest.raises(ChannelDeliveryFailed, match="does not support"):
        await SlackChannelSender(_settings()).send(attachment_only)

    oversized = _message(text="x" * 40_001)
    with pytest.raises(ChannelDeliveryFailed, match="provider limit"):
        await SlackChannelSender(_settings()).send(oversized)


async def test_sender_enforces_outbound_channel_allowlist() -> None:
    settings = SlackChannelSettings(
        signing_secret="1234567890abcdef1234567890abcdef",
        bot_token="xoxb-secret-token",
        allowed_channel_ids=("C999ABC999",),
    )

    with pytest.raises(ChannelUnauthorized, match="not allowed"):
        await SlackChannelSender(settings).send(_message())


def test_sender_requires_bot_token_and_fails_fast_without_httpx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="bot_token is required"):
        SlackChannelSender(SlackChannelSettings())

    def missing_httpx() -> None:
        raise RuntimeError("install arclith[channel]")

    monkeypatch.setattr(slack_sender, "_require_httpx", missing_httpx)
    with pytest.raises(RuntimeError, match=r"arclith\[channel\]"):
        SlackChannelSender(_settings())
