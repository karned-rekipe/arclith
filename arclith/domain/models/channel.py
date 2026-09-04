from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    NonNegativeInt,
    StringConstraints,
    field_validator,
    model_validator,
)
from uuid6 import uuid7

from arclith.domain.models.json import validate_finite_json

NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
ChannelDeliveryStatus = Literal["accepted", "sent", "delivered", "failed"]
ChannelHandlerStatus = Literal["completed", "accepted"]
ChannelDispatchStatus = Literal["completed", "accepted", "duplicate"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("channel timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _has_unsafe_storage_key_syntax(value: str) -> bool:
    return (
        "\\" in value
        or value.startswith("/")
        or value.endswith("/")
        or "//" in value
        or bool(PureWindowsPath(value).drive)
        or PurePosixPath(value).as_posix() != value
    )


class _ChannelModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("metadata", check_fields=False)
    @classmethod
    def metadata_must_be_strict_json(
        cls,
        value: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        validate_finite_json(value)
        return value


class ChannelAttachment(_ChannelModel):
    """Provider-neutral attachment metadata without embedded binary content."""

    kind: NonEmptyString
    name: NonEmptyString | None = None
    content_type: NonEmptyString | None = None
    url: str | None = None
    storage_key: str | None = None
    size: NonNegativeInt | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def url_must_be_credential_free_http(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "channel attachment url must be a credential-free HTTP URL"
            )
        return normalized

    @field_validator("storage_key")
    @classmethod
    def storage_key_must_be_relative(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if (
            not normalized
            or normalized != value
            or _has_unsafe_storage_key_syntax(normalized)
            or any(part in {"", ".", ".."} for part in normalized.split("/"))
        ):
            raise ValueError(
                "channel attachment storage_key must be a normalized relative POSIX path"
            )
        return normalized

    @model_validator(mode="after")
    def exactly_one_locator_is_required(self) -> "ChannelAttachment":
        if (self.url is None) == (self.storage_key is None):
            raise ValueError(
                "channel attachment requires exactly one of url or storage_key"
            )
        return self


class ChannelIdentity(_ChannelModel):
    """Identity asserted by a provider before application-level resolution."""

    provider: NonEmptyString
    external_user_id: NonEmptyString
    display_name: NonEmptyString | None = None
    external_tenant_id: NonEmptyString | None = None
    external_workspace_id: NonEmptyString | None = None


class ResolvedChannelIdentity(_ChannelModel):
    """Explicit mapping from a provider identity to application coordinates."""

    user_id: NonEmptyString
    tenant_id: NonEmptyString | None = None


class ChannelIncomingMessage(_ChannelModel):
    """Normalized message delivered by a channel adapter to the application."""

    channel: NonEmptyString
    provider_event_id: NonEmptyString
    conversation_id: NonEmptyString
    thread_id: NonEmptyString | None = None
    sender: ChannelIdentity
    text: str | None = None
    attachments: tuple[ChannelAttachment, ...] = ()
    received_at: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("received_at")
    @classmethod
    def received_at_must_be_utc(cls, value: datetime) -> datetime:
        return _validate_utc_datetime(value)

    @model_validator(mode="after")
    def validate_content_and_provider(self) -> "ChannelIncomingMessage":
        if self.text is not None and not self.text.strip():
            raise ValueError("channel incoming text must not be blank")
        if self.text is None and not self.attachments:
            raise ValueError("channel incoming message requires text or attachments")
        if self.channel != self.sender.provider:
            raise ValueError("channel must match sender.provider")
        return self


class ChannelOutgoingMessage(_ChannelModel):
    """Provider-neutral response passed to an outbound channel sender."""

    message_id: NonEmptyString = Field(default_factory=lambda: str(uuid7()))
    channel: NonEmptyString
    conversation_id: NonEmptyString
    thread_id: NonEmptyString | None = None
    recipient_id: NonEmptyString | None = None
    text: str | None = None
    attachments: tuple[ChannelAttachment, ...] = ()
    reply_to: NonEmptyString | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def text_or_attachments_are_required(self) -> "ChannelOutgoingMessage":
        if self.text is not None and not self.text.strip():
            raise ValueError("channel outgoing text must not be blank")
        if self.text is None and not self.attachments:
            raise ValueError("channel outgoing message requires text or attachments")
        return self


class ChannelDeliveryReceipt(_ChannelModel):
    """Provider-neutral result for one outbound message delivery."""

    message_id: NonEmptyString
    provider_message_id: NonEmptyString | None = None
    status: ChannelDeliveryStatus
    timestamp: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_utc(cls, value: datetime) -> datetime:
        return _validate_utc_datetime(value)


class ChannelHandlerResult(_ChannelModel):
    """Application result independent from any provider acknowledgement protocol."""

    status: ChannelHandlerStatus = "completed"
    responses: tuple[ChannelOutgoingMessage, ...] = ()

    @model_validator(mode="after")
    def accepted_result_has_no_immediate_responses(self) -> "ChannelHandlerResult":
        if self.status == "accepted" and self.responses:
            raise ValueError(
                "accepted channel results cannot contain immediate responses"
            )
        return self


class ChannelDispatchResult(_ChannelModel):
    """Transport-neutral outcome returned by the channel dispatcher."""

    status: ChannelDispatchStatus
    identity: ResolvedChannelIdentity | None = None
    receipts: tuple[ChannelDeliveryReceipt, ...] = ()

    @model_validator(mode="after")
    def validate_status_payload(self) -> "ChannelDispatchResult":
        if self.status == "duplicate" and (self.identity is not None or self.receipts):
            raise ValueError(
                "duplicate channel results cannot include identity or receipts"
            )
        if self.status == "accepted" and self.receipts:
            raise ValueError(
                "accepted channel results cannot include delivery receipts"
            )
        return self
