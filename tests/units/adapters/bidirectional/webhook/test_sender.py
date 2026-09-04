from __future__ import annotations

import httpx
import pytest

import arclith.adapters.bidirectional.webhook.sender as webhook_sender
from arclith.adapters.bidirectional.webhook import (
    WebhookCallbackSender,
    WebhookResponseCollector,
)
from arclith.domain.errors.channel import (
    ChannelDeliveryFailed,
    ChannelRateLimited,
    ChannelUnavailable,
)
from arclith.domain.models.channel import ChannelOutgoingMessage
from arclith.infrastructure.settings.channel import WebhookChannelSettings


def _settings() -> WebhookChannelSettings:
    return WebhookChannelSettings(
        response_mode="callback",
        callback_url="https://hooks.example.test/arclith",
        callback_allowed_host="hooks.example.test",
    )


def _message(*, channel: str = "webhook") -> ChannelOutgoingMessage:
    return ChannelOutgoingMessage(
        message_id="msg-1",
        channel=channel,
        conversation_id="conversation-1",
        text="pong",
    )


async def test_response_collector_returns_inline_accepted_receipt() -> None:
    collector = WebhookResponseCollector()

    receipt = await collector.send(_message())

    assert receipt.status == "accepted"
    assert collector.messages == (_message(),)


async def test_callback_sender_posts_to_the_server_configured_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://hooks.example.test/arclith"
        assert request.headers["X-Arclith-Message-Id"] == "msg-1"
        assert b'"callback_url"' not in request.content
        return httpx.Response(204, headers={"X-Arclith-Message-Id": "remote-1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await WebhookCallbackSender(_settings(), client=client).send(
            _message()
        )

    assert receipt.status == "delivered"
    assert receipt.provider_message_id == "remote-1"


async def test_callback_sender_ignores_a_blank_provider_message_id() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"X-Arclith-Message-Id": "   "},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        receipt = await WebhookCallbackSender(_settings(), client=client).send(
            _message()
        )

    assert receipt.provider_message_id is None


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (302, ChannelDeliveryFailed),
        (400, ChannelDeliveryFailed),
        (500, ChannelUnavailable),
    ],
)
async def test_callback_sender_maps_rejections_without_response_details(
    status_code: int,
    error_type: type[Exception],
) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(status_code, text="secret provider body")
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(error_type) as captured:
            await WebhookCallbackSender(_settings(), client=client).send(_message())

    assert "secret provider body" not in str(captured.value)
    assert "hooks.example.test" not in str(captured.value)


async def test_callback_sender_exposes_numeric_retry_after_only() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(429, headers={"Retry-After": "2.5"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ChannelRateLimited) as captured:
            await WebhookCallbackSender(_settings(), client=client).send(_message())

    assert captured.value.retry_after_seconds == 2.5


async def test_callback_sender_maps_transport_timeouts() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider secret timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(ChannelUnavailable) as captured:
            await WebhookCallbackSender(_settings(), client=client).send(_message())

    assert "provider secret timeout" not in str(captured.value)


async def test_webhook_senders_reject_other_channels() -> None:
    message = _message(channel="slack")

    with pytest.raises(ChannelDeliveryFailed, match="webhook channel"):
        await WebhookResponseCollector().send(message)
    with pytest.raises(ChannelDeliveryFailed, match="webhook channel"):
        await WebhookCallbackSender(_settings()).send(message)


def test_callback_sender_requires_callback_mode() -> None:
    with pytest.raises(ValueError, match="callback mode"):
        WebhookCallbackSender(WebhookChannelSettings())


def test_callback_sender_fails_fast_when_httpx_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_httpx() -> None:
        raise RuntimeError("install arclith[channel]")

    monkeypatch.setattr(webhook_sender, "_require_httpx", missing_httpx)

    with pytest.raises(RuntimeError, match=r"arclith\[channel\]"):
        WebhookCallbackSender(_settings())
