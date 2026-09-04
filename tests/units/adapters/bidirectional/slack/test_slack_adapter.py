from __future__ import annotations

import json
from pathlib import Path

import pytest

from arclith.adapters.bidirectional.memory import (
    MemoryChannel,
    MemoryChannelIdentityResolver,
)
from arclith.adapters.bidirectional.slack import (
    SlackChannelAdapter,
    SlackInvalidEvent,
    SlackInvalidPayload,
    SlackPayloadTooLarge,
    SlackUnsupportedMediaType,
    sign_slack_payload,
)
from arclith.domain.errors.channel import (
    ChannelUnauthorized,
    InvalidChannelSignature,
)
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
            user_id="user-1",
            tenant_id="tenant-1",
        )
        self.messages.append(message)
        return self.result


class RecordingSender(ChannelSender):
    def __init__(self) -> None:
        self.messages: list[ChannelOutgoingMessage] = []

    async def send(self, message: ChannelOutgoingMessage) -> ChannelDeliveryReceipt:
        self.messages.append(message)
        return ChannelDeliveryReceipt(
            message_id=message.message_id,
            provider_message_id="1700000003.000400",
            status="delivered",
        )


def _fixture(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def _headers(body: bytes) -> dict[str, str]:
    return {
        "Content-Type": "application/json; charset=utf-8",
        "X-Slack-Request-Timestamp": "1000",
        "X-Slack-Signature": sign_slack_payload(_SECRET, 1_000, body),
    }


def _settings(**overrides: object) -> SlackChannelSettings:
    return SlackChannelSettings.model_validate(
        {"signing_secret": _SECRET, "bot_token": "xoxb-test-token", **overrides}
    )


def _resolver(*, enterprise: bool = False) -> MemoryChannelIdentityResolver:
    resolver = MemoryChannelIdentityResolver()
    resolver.register(
        ChannelIdentity(
            provider="slack",
            external_user_id="U123ABC456",
            external_tenant_id="E123ABC456" if enterprise else "T123ABC456",
            external_workspace_id="T123ABC456",
        ),
        ResolvedChannelIdentity(user_id="user-1", tenant_id="tenant-1"),
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


def _adapter(
    body_name: str,
    handler: RecordingHandler,
    *,
    settings: SlackChannelSettings | None = None,
    resolver: MemoryChannelIdentityResolver | None = None,
    event_store: MemoryChannel | None = None,
    sender: ChannelSender | None = None,
) -> tuple[SlackChannelAdapter, bytes]:
    body = _fixture(body_name)
    return (
        SlackChannelAdapter(
            settings or _settings(),
            handler,
            resolver or _resolver(),
            event_store or MemoryChannel(),
            sender=sender or RecordingSender(),
            clock=lambda: 1_000,
        ),
        body,
    )


async def test_slack_adapter_normalizes_message_attachment_and_deduplicates() -> None:
    handler = RecordingHandler(ChannelHandlerResult(responses=(_response(),)))
    sender = RecordingSender()
    adapter, body = _adapter("message.json", handler, sender=sender)
    headers = {**_headers(body), "X-Slack-Retry-Num": "1"}
    headers["X-Slack-Retry-Reason"] = "http_timeout"

    result = await adapter.dispatch(body, headers)
    duplicate = await adapter.dispatch(body, headers)

    assert result.status == "completed"
    assert result.receipts[0].provider_message_id == "1700000003.000400"
    assert duplicate.status == "duplicate"
    assert len(handler.messages) == 1
    message = handler.messages[0]
    assert message.provider_event_id == "Ev123ABC456"
    assert message.conversation_id == "C123ABC456"
    assert message.thread_id == "1699999999.000001"
    assert message.sender.external_workspace_id == "T123ABC456"
    assert message.metadata["retry_num"] == "1"
    assert message.metadata["retry_reason"] == "http_timeout"
    assert message.attachments[0].metadata == {"slack_file_id": "F123ABC456"}
    assert sender.messages == [_response()]


async def test_slack_adapter_handles_challenge_without_application_dispatch() -> None:
    handler = RecordingHandler(ChannelHandlerResult())
    adapter, body = _adapter("url_verification.json", handler)

    result = await adapter.dispatch(body, _headers(body))

    assert result.model_dump() == {"challenge": "challenge-value"}
    assert handler.messages == []


async def test_slack_adapter_normalizes_app_mention_and_enterprise_identity() -> None:
    handler = RecordingHandler(ChannelHandlerResult(status="accepted"))
    adapter, body = _adapter(
        "app_mention.json",
        handler,
        resolver=_resolver(enterprise=True),
    )

    result = await adapter.dispatch(body, _headers(body))

    assert result.status == "accepted"
    assert handler.messages[0].text == "<@U0BOT1234> donne-moi le statut"
    assert handler.messages[0].thread_id == "1700000001.000200"
    assert handler.messages[0].sender.external_tenant_id == "E123ABC456"


@pytest.mark.parametrize("fixture_name", ["bot_message.json"])
async def test_slack_adapter_ignores_bot_events_without_claim_or_dispatch(
    fixture_name: str,
) -> None:
    handler = RecordingHandler(ChannelHandlerResult())
    event_store = MemoryChannel()
    adapter, body = _adapter(
        fixture_name,
        handler,
        event_store=event_store,
    )

    first = await adapter.dispatch(body, _headers(body))
    second = await adapter.dispatch(body, _headers(body))

    assert first.status == second.status == "ignored"
    assert handler.messages == []


async def test_slack_adapter_ignores_unknown_events_and_empty_messages() -> None:
    handler = RecordingHandler(ChannelHandlerResult())
    adapter, _ = _adapter("message.json", handler)
    unknown = json.dumps(
        {
            "type": "event_callback",
            "team_id": "T123ABC456",
            "event_id": "EvUNKNOWN1",
            "event": {"type": "reaction_added"},
        }
    ).encode()
    empty = json.dumps(
        {
            "type": "event_callback",
            "team_id": "T123ABC456",
            "event_id": "EvEMPTY001",
            "event": {
                "type": "message",
                "user": "U123ABC456",
                "text": "  ",
                "ts": "1700000000.1",
                "channel": "C123ABC456",
            },
        }
    ).encode()

    assert (await adapter.dispatch(unknown, _headers(unknown))).status == "ignored"
    assert (await adapter.dispatch(empty, _headers(empty))).status == "ignored"
    assert handler.messages == []


async def test_slack_adapter_drops_unrecognized_retry_metadata() -> None:
    handler = RecordingHandler(ChannelHandlerResult())
    adapter, body = _adapter("message.json", handler)

    await adapter.dispatch(
        body,
        {
            **_headers(body),
            "X-Slack-Retry-Num": "not-a-number",
            "X-Slack-Retry-Reason": "provider-private-detail",
        },
    )

    assert "retry_num" not in handler.messages[0].metadata
    assert "retry_reason" not in handler.messages[0].metadata


@pytest.mark.parametrize(
    "settings",
    [
        _settings(workspace_id="T999ABC999"),
        _settings(allowed_channel_ids=["C999ABC999"]),
    ],
)
async def test_slack_adapter_enforces_workspace_and_channel_allowlists(
    settings: SlackChannelSettings,
) -> None:
    adapter, body = _adapter(
        "message.json",
        RecordingHandler(ChannelHandlerResult()),
        settings=settings,
    )

    with pytest.raises(ChannelUnauthorized):
        await adapter.dispatch(body, _headers(body))


async def test_slack_adapter_authenticates_raw_body_before_parsing() -> None:
    adapter, body = _adapter(
        "message.json",
        RecordingHandler(ChannelHandlerResult()),
    )

    with pytest.raises(InvalidChannelSignature):
        await adapter.dispatch(
            b"not-json",
            {**_headers(body), "X-Slack-Signature": "v0=invalid"},
        )


@pytest.mark.parametrize(
    ("body", "headers", "error_type"),
    [
        (
            _fixture("message.json"),
            {"Content-Type": "text/plain"},
            SlackUnsupportedMediaType,
        ),
        (b"invalid", {"Content-Type": "application/json"}, SlackInvalidPayload),
    ],
)
async def test_slack_adapter_rejects_invalid_transport_payloads(
    body: bytes,
    headers: dict[str, str],
    error_type: type[Exception],
) -> None:
    adapter, _ = _adapter(
        "message.json",
        RecordingHandler(ChannelHandlerResult()),
    )

    with pytest.raises(error_type):
        await adapter.dispatch(body, {**_headers(body), **headers})


async def test_slack_adapter_rejects_oversized_body_and_file_without_url() -> None:
    body = _fixture("message.json")
    adapter, _ = _adapter(
        "message.json",
        RecordingHandler(ChannelHandlerResult()),
        settings=_settings(max_payload_bytes=len(body)),
    )

    with pytest.raises(SlackPayloadTooLarge):
        await adapter.dispatch(body + b" ", _headers(body + b" "))

    payload = json.loads(body)
    payload["event"]["files"][0].pop("url_private_download")
    without_url = json.dumps(payload).encode()
    with pytest.raises(SlackInvalidEvent, match="missing a private URL"):
        await adapter.dispatch(without_url, _headers(without_url))
