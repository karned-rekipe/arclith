from __future__ import annotations

import json

import pytest

from arclith.adapters.bidirectional.memory import (
    MemoryChannel,
    MemoryChannelIdentityResolver,
)
from arclith.adapters.bidirectional.webhook import (
    WebhookChannelAdapter,
    WebhookInvalidPayload,
    WebhookMissingEventId,
    WebhookPayloadTooLarge,
    WebhookResponseModeError,
    WebhookUnsupportedMediaType,
    sign_webhook_payload,
)
from arclith.domain.errors.channel import InvalidChannelSignature
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

_SECRET = "a-secure-webhook-secret-with-32-bytes"


class RecordingHandler(ChannelMessageHandler):
    def __init__(self, result: ChannelHandlerResult) -> None:
        self.result = result
        self.messages: list[ChannelIncomingMessage] = []

    async def handle(
        self,
        message: ChannelIncomingMessage,
        identity: ResolvedChannelIdentity,
    ) -> ChannelHandlerResult:
        assert identity == ResolvedChannelIdentity(
            user_id="user-1", tenant_id="tenant-1"
        )
        self.messages.append(message)
        return self.result


class RecordingSender(ChannelSender):
    def __init__(self) -> None:
        self.messages: list[ChannelOutgoingMessage] = []

    async def send(self, message: ChannelOutgoingMessage) -> ChannelDeliveryReceipt:
        self.messages.append(message)
        return ChannelDeliveryReceipt(message_id=message.message_id, status="delivered")


def _payload(**overrides: object) -> bytes:
    payload: dict[str, object] = {
        "sender_id": "external-1",
        "external_tenant_id": "provider-tenant",
        "conversation_id": "conversation-1",
        "thread_id": "thread-1",
        "text": "ping",
        "metadata": {"trace_id": "trace-1", "ignored": "private"},
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


def _headers(
    body: bytes,
    *,
    event_id: str | None = "event-1",
) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-Arclith-Timestamp": "1000",
        "X-Arclith-Signature": sign_webhook_payload(_SECRET, 1_000, body),
    }
    if event_id is not None:
        headers["X-Arclith-Event-Id"] = event_id
    return headers


def _resolver() -> MemoryChannelIdentityResolver:
    resolver = MemoryChannelIdentityResolver()
    resolver.register(
        ChannelIdentity(
            provider="webhook",
            external_user_id="external-1",
            external_tenant_id="provider-tenant",
        ),
        ResolvedChannelIdentity(user_id="user-1", tenant_id="tenant-1"),
    )
    return resolver


def _response() -> ChannelOutgoingMessage:
    return ChannelOutgoingMessage(
        message_id="response-1",
        channel="webhook",
        conversation_id="conversation-1",
        text="pong",
    )


def _settings(**overrides: object) -> WebhookChannelSettings:
    return WebhookChannelSettings.model_validate(
        {
            "secret": _SECRET,
            "metadata_allowlist": ["trace_id"],
            **overrides,
        }
    )


async def test_webhook_adapter_normalizes_allowlisted_payload_and_deduplicates() -> (
    None
):
    body = _payload()
    handler = RecordingHandler(ChannelHandlerResult(responses=(_response(),)))
    adapter = WebhookChannelAdapter(
        _settings(),
        handler,
        _resolver(),
        MemoryChannel(),
        clock=lambda: 1_000,
    )

    result = await adapter.dispatch(body, _headers(body))
    duplicate = await adapter.dispatch(body, _headers(body))

    assert result.status == "completed"
    assert result.responses == (_response(),)
    assert result.receipts[0].status == "accepted"
    assert duplicate.status == "duplicate"
    assert len(handler.messages) == 1
    message = handler.messages[0]
    assert message.provider_event_id == "event-1"
    assert message.metadata == {"trace_id": "trace-1"}
    assert message.sender.external_user_id == "external-1"


async def test_webhook_adapter_authenticates_raw_body_before_parsing() -> None:
    invalid_body = b"not-json"
    adapter = WebhookChannelAdapter(
        _settings(),
        RecordingHandler(ChannelHandlerResult()),
        _resolver(),
        MemoryChannel(),
        clock=lambda: 1_000,
    )

    with pytest.raises(InvalidChannelSignature):
        await adapter.dispatch(
            invalid_body,
            {
                **_headers(_payload()),
                "X-Arclith-Signature": "sha256=invalid",
            },
        )


@pytest.mark.parametrize(
    ("body", "headers", "error_type"),
    [
        (_payload(), {"Content-Type": "text/plain"}, WebhookUnsupportedMediaType),
        (b"invalid", {"Content-Type": "application/json"}, WebhookInvalidPayload),
    ],
)
async def test_webhook_adapter_rejects_invalid_transport_payloads_without_signature(
    body: bytes,
    headers: dict[str, str],
    error_type: type[Exception],
) -> None:
    adapter = WebhookChannelAdapter(
        WebhookChannelSettings(),
        RecordingHandler(ChannelHandlerResult()),
        _resolver(),
        MemoryChannel(),
    )
    effective_headers = {"X-Arclith-Event-Id": "event-1", **headers}

    with pytest.raises(error_type):
        await adapter.dispatch(body, effective_headers)


async def test_webhook_adapter_rejects_missing_event_id_and_oversized_body() -> None:
    body = _payload()
    adapter = WebhookChannelAdapter(
        WebhookChannelSettings(max_payload_bytes=len(body)),
        RecordingHandler(ChannelHandlerResult()),
        _resolver(),
        MemoryChannel(),
    )

    with pytest.raises(WebhookMissingEventId):
        await adapter.dispatch(body, {"Content-Type": "application/json"})
    with pytest.raises(WebhookPayloadTooLarge):
        await adapter.dispatch(
            body + b" ",
            {
                "Content-Type": "application/json",
                "X-Arclith-Event-Id": "event-1",
            },
        )


@pytest.mark.parametrize(
    ("mode", "handler_status"),
    [("sync", "accepted"), ("accepted", "completed")],
)
async def test_webhook_adapter_enforces_response_mode_contract(
    mode: str,
    handler_status: str,
) -> None:
    body = _payload()
    adapter = WebhookChannelAdapter(
        WebhookChannelSettings(response_mode=mode),
        RecordingHandler(ChannelHandlerResult(status=handler_status)),
        _resolver(),
        MemoryChannel(),
    )

    with pytest.raises(WebhookResponseModeError):
        await adapter.dispatch(body, _headers(body))


async def test_webhook_adapter_accepts_only_durable_handler_acknowledgement() -> None:
    body = _payload()
    adapter = WebhookChannelAdapter(
        WebhookChannelSettings(response_mode="accepted"),
        RecordingHandler(ChannelHandlerResult(status="accepted")),
        _resolver(),
        MemoryChannel(),
    )

    result = await adapter.dispatch(body, _headers(body))

    assert result.status == "accepted"
    assert result.responses == ()
    assert result.receipts == ()


async def test_webhook_adapter_delivers_completed_callback_server_side() -> None:
    body = _payload()
    sender = RecordingSender()
    settings = WebhookChannelSettings(
        response_mode="callback",
        callback_url="https://hooks.example.test/arclith",
        callback_allowed_host="hooks.example.test",
    )
    adapter = WebhookChannelAdapter(
        settings,
        RecordingHandler(ChannelHandlerResult(responses=(_response(),))),
        _resolver(),
        MemoryChannel(),
        callback_sender=sender,
    )

    result = await adapter.dispatch(body, _headers(body))

    assert result.status == "completed"
    assert result.responses == ()
    assert result.receipts[0].status == "delivered"
    assert sender.messages == [_response()]


def test_webhook_adapter_rejects_callback_sender_outside_callback_mode() -> None:
    with pytest.raises(ValueError, match="response_mode=callback"):
        WebhookChannelAdapter(
            WebhookChannelSettings(),
            RecordingHandler(ChannelHandlerResult()),
            _resolver(),
            MemoryChannel(),
            callback_sender=RecordingSender(),
        )
