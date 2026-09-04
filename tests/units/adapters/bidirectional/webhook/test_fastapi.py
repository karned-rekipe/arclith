from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arclith.adapters.bidirectional.memory import (
    MemoryChannel,
    MemoryChannelIdentityResolver,
)
from arclith.adapters.bidirectional.webhook import build_webhook_router
from arclith.domain.errors.channel import ChannelRateLimited
from arclith.domain.models.channel import (
    ChannelDeliveryReceipt,
    ChannelHandlerResult,
    ChannelIdentity,
    ChannelIncomingMessage,
    ChannelOutgoingMessage,
    ResolvedChannelIdentity,
)
from arclith.domain.ports.inbound.channel import ChannelMessageHandler
from arclith.domain.ports.outbound.channel import ChannelSender
from arclith.infrastructure.settings.channel import WebhookChannelSettings


class StaticHandler(ChannelMessageHandler):
    def __init__(self, result: ChannelHandlerResult) -> None:
        self.result = result

    async def handle(
        self,
        message: ChannelIncomingMessage,
        identity: ResolvedChannelIdentity,
    ) -> ChannelHandlerResult:
        return self.result


class RateLimitedSender(ChannelSender):
    async def send(self, message: ChannelOutgoingMessage) -> ChannelDeliveryReceipt:
        raise ChannelRateLimited("hidden callback detail", retry_after_seconds=1.2)


def _resolver() -> MemoryChannelIdentityResolver:
    resolver = MemoryChannelIdentityResolver()
    resolver.register(
        ChannelIdentity(provider="webhook", external_user_id="external-1"),
        ResolvedChannelIdentity(user_id="user-1"),
    )
    return resolver


def _response() -> ChannelOutgoingMessage:
    return ChannelOutgoingMessage(
        message_id="response-1",
        channel="webhook",
        conversation_id="conversation-1",
        text="pong",
    )


def _client(
    settings: WebhookChannelSettings,
    result: ChannelHandlerResult,
    *,
    sender: ChannelSender | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(
        build_webhook_router(
            settings,
            StaticHandler(result),
            _resolver(),
            MemoryChannel(),
            callback_sender=sender,
        )
    )
    return TestClient(app)


def _payload() -> bytes:
    return json.dumps(
        {
            "sender_id": "external-1",
            "conversation_id": "conversation-1",
            "text": "ping",
        }
    ).encode()


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Arclith-Event-Id": "event-1",
    }


def test_fastapi_router_declares_success_and_error_responses() -> None:
    client = _client(WebhookChannelSettings(), ChannelHandlerResult())

    operation = client.get("/openapi.json").json()["paths"]["/channels/webhook"]["post"]

    assert set(operation["responses"]) == {
        "200",
        "202",
        "400",
        "401",
        "403",
        "413",
        "415",
        "422",
        "429",
        "500",
        "502",
        "503",
    }


def test_fastapi_router_returns_sync_and_accepted_contracts() -> None:
    sync = _client(
        WebhookChannelSettings(),
        ChannelHandlerResult(responses=(_response(),)),
    ).post("/channels/webhook", content=_payload(), headers=_headers())
    accepted = _client(
        WebhookChannelSettings(response_mode="accepted"),
        ChannelHandlerResult(status="accepted"),
    ).post("/channels/webhook", content=_payload(), headers=_headers())

    assert sync.status_code == 200
    assert sync.json()["status"] == "completed"
    assert sync.json()["responses"][0]["text"] == "pong"
    assert accepted.status_code == 202
    assert accepted.json() == {"status": "accepted", "responses": [], "receipts": []}


@pytest.mark.parametrize(
    ("headers", "expected_status", "expected_code"),
    [
        ({"Content-Type": "text/plain"}, 415, "unsupported_media_type"),
        ({"Content-Type": "application/json"}, 400, "missing_event_id"),
    ],
)
def test_fastapi_router_maps_transport_errors_without_internal_details(
    headers: dict[str, str],
    expected_status: int,
    expected_code: str,
) -> None:
    response = _client(WebhookChannelSettings(), ChannelHandlerResult()).post(
        "/channels/webhook",
        content=_payload(),
        headers=headers,
    )

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code


def test_fastapi_router_maps_callback_rate_limit_and_retry_after() -> None:
    settings = WebhookChannelSettings(
        response_mode="callback",
        callback_url="https://hooks.example.test/arclith",
        callback_allowed_host="hooks.example.test",
    )
    response = _client(
        settings,
        ChannelHandlerResult(responses=(_response(),)),
        sender=RateLimitedSender(),
    ).post("/channels/webhook", content=_payload(), headers=_headers())

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "2"
    assert response.json() == {
        "code": "callback_rate_limited",
        "detail": "Webhook callback is rate limited",
    }


def test_fastapi_router_streams_and_rejects_oversized_payloads() -> None:
    client = _client(
        WebhookChannelSettings(max_payload_bytes=4),
        ChannelHandlerResult(),
    )

    response = client.post(
        "/channels/webhook",
        content=_payload(),
        headers=_headers(),
    )

    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"
