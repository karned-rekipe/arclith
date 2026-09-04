from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    JsonValue,
    NonNegativeInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from arclith.domain.models.channel import ChannelDeliveryReceipt
from arclith.domain.models.json import validate_finite_json

NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class _SlackProviderModel(BaseModel):
    """Typed provider input while tolerating additive Slack fields."""

    model_config = ConfigDict(extra="ignore", frozen=True)


class SlackEnvelope(_SlackProviderModel):
    type: NonEmptyString


class SlackUrlVerificationPayload(_SlackProviderModel):
    type: Literal["url_verification"]
    challenge: NonEmptyString


class SlackEventCallbackPayload(_SlackProviderModel):
    type: Literal["event_callback"]
    team_id: NonEmptyString
    enterprise_id: NonEmptyString | None = None
    event_id: NonEmptyString
    event_time: int | None = None
    event: dict[str, JsonValue]

    @field_validator("event")
    @classmethod
    def event_must_be_finite_json(
        cls,
        value: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        validate_finite_json(value)
        return value


class SlackFilePayload(_SlackProviderModel):
    id: NonEmptyString
    name: NonEmptyString | None = None
    mimetype: NonEmptyString | None = None
    size: NonNegativeInt | None = None
    url_private: NonEmptyString | None = None
    url_private_download: NonEmptyString | None = None


class SlackMessageEvent(_SlackProviderModel):
    type: Literal["message", "app_mention"]
    user: NonEmptyString | None = None
    text: str | None = None
    ts: NonEmptyString
    channel: NonEmptyString
    thread_ts: NonEmptyString | None = None
    event_ts: NonEmptyString | None = None
    subtype: NonEmptyString | None = None
    bot_id: NonEmptyString | None = None
    app_id: NonEmptyString | None = None
    files: tuple[SlackFilePayload, ...] = ()


class SlackPostMessageResponse(_SlackProviderModel):
    ok: bool
    channel: NonEmptyString | None = None
    ts: NonEmptyString | None = None
    error: NonEmptyString | None = None


class SlackChallengeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    challenge: NonEmptyString


class SlackEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["completed", "accepted", "duplicate", "ignored"]
    receipts: tuple[ChannelDeliveryReceipt, ...] = ()

    @model_validator(mode="after")
    def receipts_require_completed_status(self) -> "SlackEventResponse":
        if self.status != "completed" and self.receipts:
            raise ValueError("only completed Slack events can include receipts")
        return self


class SlackErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: NonEmptyString
    detail: NonEmptyString
