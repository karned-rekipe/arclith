from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from arclith.domain.errors.channel import ChannelRateLimited
from arclith.domain.models.channel import (
    ChannelAttachment,
    ChannelDeliveryReceipt,
    ChannelDispatchResult,
    ChannelHandlerResult,
    ChannelIdentity,
    ChannelIncomingMessage,
    ChannelOutgoingMessage,
    ResolvedChannelIdentity,
)


def _identity() -> ChannelIdentity:
    return ChannelIdentity(provider="slack", external_user_id="U123")


def _outgoing() -> ChannelOutgoingMessage:
    return ChannelOutgoingMessage(
        channel="slack",
        conversation_id="C123",
        text="pong",
    )


def test_channel_attachment_accepts_one_safe_locator() -> None:
    by_url = ChannelAttachment(
        kind="image",
        url="https://files.example.test/a.png",
        storage_key=None,
        metadata={"width": 320},
    )
    by_key = ChannelAttachment(
        kind="document",
        url=None,
        storage_key="tenant-a/report.pdf",
    )

    assert by_url.url == "https://files.example.test/a.png"
    assert by_key.storage_key == "tenant-a/report.pdf"


@pytest.mark.parametrize(
    "values",
    [
        {"kind": "image"},
        {
            "kind": "image",
            "url": "https://files.example.test/a.png",
            "storage_key": "a.png",
        },
        {"kind": "image", "url": "file:///tmp/a.png"},
        {"kind": "image", "url": "https://user:secret@example.test/a.png"},
        {"kind": "image", "url": "https://example.test/a.png?token=secret"},
        {"kind": "image", "storage_key": "../secret.txt"},
        {"kind": "image", "storage_key": "/absolute/path"},
        {"kind": "image", "storage_key": "C:/absolute/path"},
    ],
)
def test_channel_attachment_rejects_unsafe_or_ambiguous_locator(
    values: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        ChannelAttachment.model_validate(values)


def test_channel_incoming_message_normalizes_aware_timestamps_to_utc() -> None:
    message = ChannelIncomingMessage(
        channel="slack",
        provider_event_id="Ev123",
        conversation_id="C123",
        sender=_identity(),
        text="hello",
        received_at=datetime(2026, 9, 4, 12, tzinfo=timezone(timedelta(hours=2))),
        metadata={"retry": False, "attempt": 1},
    )

    assert message.received_at == datetime(2026, 9, 4, 10, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"text": " "}, "blank"),
        ({"text": None}, "text or attachments"),
        ({"channel": "webhook"}, "sender.provider"),
        ({"received_at": datetime(2026, 9, 4, 10)}, "timezone-aware"),
    ],
)
def test_channel_incoming_message_rejects_invalid_contract(
    overrides: dict[str, object],
    match: str,
) -> None:
    values: dict[str, object] = {
        "channel": "slack",
        "provider_event_id": "Ev123",
        "conversation_id": "C123",
        "sender": _identity(),
        "text": "hello",
    }
    values.update(overrides)

    with pytest.raises(ValidationError, match=match):
        ChannelIncomingMessage.model_validate(values)


def test_channel_messages_accept_attachment_only_content() -> None:
    attachment = ChannelAttachment(kind="image", storage_key="uploads/a.png")

    incoming = ChannelIncomingMessage(
        channel="slack",
        provider_event_id="Ev123",
        conversation_id="C123",
        sender=_identity(),
        attachments=(attachment,),
    )
    outgoing = ChannelOutgoingMessage(
        channel="slack",
        conversation_id="C123",
        attachments=(attachment,),
    )

    assert incoming.text is None
    assert outgoing.text is None


def test_channel_outgoing_message_has_uuid7_identifier_and_rejects_blank_text() -> None:
    message = _outgoing()

    assert len(message.message_id) == 36
    with pytest.raises(ValidationError, match="blank"):
        ChannelOutgoingMessage(
            channel="slack",
            conversation_id="C123",
            text=" ",
        )
    with pytest.raises(ValidationError, match="text or attachments"):
        ChannelOutgoingMessage(channel="slack", conversation_id="C123")


def test_channel_models_are_strict_and_frozen() -> None:
    identity = _identity()

    with pytest.raises(ValidationError, match="extra_forbidden"):
        ChannelIdentity.model_validate(
            {"provider": "slack", "external_user_id": "U123", "token": "secret"}
        )
    with pytest.raises(ValidationError, match="frozen_instance"):
        identity.external_user_id = "U456"


def test_channel_metadata_rejects_non_finite_nested_numbers() -> None:
    with pytest.raises(ValidationError, match="must be finite"):
        ChannelIncomingMessage(
            channel="slack",
            provider_event_id="Ev123",
            conversation_id="C123",
            sender=_identity(),
            text="hello",
            metadata={"provider": {"score": float("nan")}},
        )


def test_channel_result_invariants_reject_incompatible_payloads() -> None:
    identity = ResolvedChannelIdentity(user_id="user-1", tenant_id="tenant-a")
    receipt = ChannelDeliveryReceipt(
        message_id="msg-1",
        provider_message_id="provider-1",
        status="delivered",
    )

    with pytest.raises(ValidationError, match="immediate responses"):
        ChannelHandlerResult(status="accepted", responses=(_outgoing(),))
    with pytest.raises(ValidationError, match="identity or receipts"):
        ChannelDispatchResult(status="duplicate", identity=identity)
    with pytest.raises(ValidationError, match="delivery receipts"):
        ChannelDispatchResult(status="accepted", receipts=(receipt,))


def test_channel_delivery_receipt_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        ChannelDeliveryReceipt(
            message_id="msg-1",
            status="sent",
            timestamp=datetime(2026, 9, 4, 10),
        )


def test_channel_rate_limit_exposes_retry_delay_without_changing_message() -> None:
    error = ChannelRateLimited("slow down", retry_after_seconds=2.5)

    assert str(error) == "slow down"
    assert error.retry_after_seconds == 2.5
