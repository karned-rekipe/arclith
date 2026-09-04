from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from arclith.adapters.bidirectional.memory import (
    MemoryChannel,
    MemoryChannelIdentityResolver,
)
from arclith.adapters.bidirectional.slack import (
    build_slack_router,
    sign_slack_payload,
)
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
from arclith.infrastructure.settings.channel import SlackChannelSettings

_FIXTURES = Path(__file__).parents[4] / "fixtures" / "slack"
_SECRET = "1234567890abcdef1234567890abcdef"


class StaticHandler(ChannelMessageHandler):
    def __init__(self, result: ChannelHandlerResult) -> None:
        self.result = result

    async def handle(
        self,
        message: ChannelIncomingMessage,
        identity: ResolvedChannelIdentity,
    ) -> ChannelHandlerResult:
        return self.result


class StaticSender(ChannelSender):
    async def send(self, message: ChannelOutgoingMessage) -> ChannelDeliveryReceipt:
        return ChannelDeliveryReceipt(
            message_id=message.message_id,
            provider_message_id="1700000001.2",
            status="delivered",
        )


class RateLimitedSender(ChannelSender):
    async def send(self, message: ChannelOutgoingMessage) -> ChannelDeliveryReceipt:
        raise ChannelRateLimited("hidden Slack detail", retry_after_seconds=1.2)


def _settings(**overrides: object) -> SlackChannelSettings:
    return SlackChannelSettings.model_validate(
        {"signing_secret": _SECRET, "bot_token": "xoxb-test-token", **overrides}
    )


def _resolver() -> MemoryChannelIdentityResolver:
    resolver = MemoryChannelIdentityResolver()
    resolver.register(
        ChannelIdentity(
            provider="slack",
            external_user_id="U123ABC456",
            external_tenant_id="T123ABC456",
            external_workspace_id="T123ABC456",
        ),
        ResolvedChannelIdentity(user_id="user-1"),
    )
    return resolver


def _response() -> ChannelOutgoingMessage:
    return ChannelOutgoingMessage(
        message_id="response-1",
        channel="slack",
        conversation_id="C123ABC456",
        thread_id="1699999999.000001",
        text="pong",
    )


def _client(
    result: ChannelHandlerResult,
    *,
    settings: SlackChannelSettings | None = None,
    sender: ChannelSender | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(
        build_slack_router(
            settings or _settings(),
            StaticHandler(result),
            _resolver(),
            MemoryChannel(),
            sender=sender or StaticSender(),
        )
    )
    return TestClient(app)


def _post(client: TestClient, fixture: str = "message.json"):
    body = (_FIXTURES / fixture).read_bytes()
    timestamp = int(time.time())
    return client.post(
        "/channels/slack/events",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Slack-Request-Timestamp": str(timestamp),
            "X-Slack-Signature": sign_slack_payload(_SECRET, timestamp, body),
        },
    )


def test_fastapi_router_declares_success_and_error_responses() -> None:
    client = _client(ChannelHandlerResult())

    operation = client.get("/openapi.json").json()["paths"]["/channels/slack/events"][
        "post"
    ]

    assert set(operation["responses"]) == {
        "200",
        "400",
        "401",
        "403",
        "413",
        "415",
        "422",
        "429",
        "502",
        "503",
    }


def test_fastapi_router_returns_challenge_and_event_acknowledgements() -> None:
    challenge = _post(_client(ChannelHandlerResult()), "url_verification.json")
    completed = _post(
        _client(ChannelHandlerResult(responses=(_response(),))),
    )
    accepted = _post(_client(ChannelHandlerResult(status="accepted")))

    assert challenge.status_code == 200
    assert challenge.json() == {"challenge": "challenge-value"}
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["receipts"][0]["status"] == "delivered"
    assert accepted.status_code == 200
    assert accepted.json() == {"status": "accepted", "receipts": []}


def test_fastapi_router_maps_transport_errors_without_internal_details() -> None:
    body = json.dumps({"type": "event_callback"}).encode()
    timestamp = int(time.time())
    response = _client(ChannelHandlerResult()).post(
        "/channels/slack/events",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Slack-Request-Timestamp": str(timestamp),
            "X-Slack-Signature": sign_slack_payload(_SECRET, timestamp, body),
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_event",
        "detail": "Slack event is invalid",
    }


def test_fastapi_router_maps_rate_limit_and_retry_after() -> None:
    response = _post(
        _client(
            ChannelHandlerResult(responses=(_response(),)),
            sender=RateLimitedSender(),
        )
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "2"
    assert response.json() == {
        "code": "slack_rate_limited",
        "detail": "Slack API is rate limited",
    }


def test_fastapi_router_streams_and_rejects_oversized_payloads() -> None:
    response = _post(
        _client(
            ChannelHandlerResult(),
            settings=_settings(max_payload_bytes=4),
        )
    )

    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"
