from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from uuid6 import uuid7


class ImmutableRecord(BaseModel):
    """Base model for a fact that may be appended but never rewritten."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    uuid: UUID = Field(
        default_factory=uuid7,
        description="Identifiant unique UUIDv7 du fait immuable.",
        examples=["01951234-5678-7abc-8ef0-123456789abc"],
    )
    occurred_at: AwareDatetime = Field(
        description="Date métier explicite à laquelle le fait s'est produit (UTC).",
        examples=["2026-03-17T10:00:00+00:00"],
    )
    recorded_at: AwareDatetime | None = Field(
        default=None,
        description="Date UTC attribuée par le store lors du premier append.",
        examples=["2026-03-17T10:00:01+00:00", None],
    )

    @field_validator("uuid", mode="before")
    @classmethod
    def coerce_uuid(cls, value: Any) -> UUID:
        if isinstance(value, UUID):
            return value
        return UUID(str(value))

    @field_validator("occurred_at", "recorded_at")
    @classmethod
    def normalize_datetime_to_utc(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None
        return value.astimezone(UTC)
