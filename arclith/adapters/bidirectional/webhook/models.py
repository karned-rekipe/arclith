from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
)

from arclith.domain.models.channel import (
    ChannelAttachment,
    ChannelDeliveryReceipt,
    ChannelOutgoingMessage,
)
from arclith.domain.models.json import validate_finite_json

NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class WebhookIncomingPayload(BaseModel):
    """Strict provider-free JSON accepted by the generic webhook adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sender_id: NonEmptyString
    sender_display_name: NonEmptyString | None = None
    external_tenant_id: NonEmptyString | None = None
    external_workspace_id: NonEmptyString | None = None
    conversation_id: NonEmptyString
    thread_id: NonEmptyString | None = None
    text: str | None = None
    attachments: tuple[ChannelAttachment, ...] = ()
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def metadata_must_be_strict_json(
        cls,
        value: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        validate_finite_json(value)
        return value


class WebhookResponse(BaseModel):
    """Stable HTTP response without resolved application identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["completed", "accepted", "duplicate"]
    responses: tuple[ChannelOutgoingMessage, ...] = ()
    receipts: tuple[ChannelDeliveryReceipt, ...] = ()


class WebhookErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: NonEmptyString
    detail: NonEmptyString
