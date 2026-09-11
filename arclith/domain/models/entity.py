from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from uuid6 import uuid7


class Entity(BaseModel):
    uuid: UUID = Field(
        default_factory=uuid7,
        description="Identifiant unique de l'entité (UUIDv7, ordonné dans le temps).",
        examples=["01951234-5678-7abc-def0-123456789abc"],
    )

    @field_validator("uuid", mode="before")
    @classmethod
    def coerce_uuid(cls, v: Any) -> UUID:
        if isinstance(v, UUID):
            return v
        return UUID(str(v))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Date et heure de création de l'entité (UTC).",
        examples=["2026-03-17T10:00:00+00:00"],
    )
    created_by: str | None = Field(
        default=None,
        description="Identifiant de l'auteur de la création (utilisateur, service…).",
        examples=["user_01951234", None],
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Date et heure de la dernière modification (UTC).",
        examples=["2026-03-17T12:30:00+00:00"],
    )
    updated_by: str | None = Field(
        default=None,
        description="Identifiant de l'auteur de la dernière modification.",
        examples=["user_01951234", None],
    )
    deleted_at: datetime | None = Field(
        default=None,
        description="Date et heure de suppression logique (None si l'entité est active).",
        examples=["2026-03-17T18:00:00+00:00", None],
    )
    deleted_by: str | None = Field(
        default=None,
        description="Identifiant de l'auteur de la suppression logique.",
        examples=["user_01951234", None],
    )
    version: int = Field(
        default=1,
        description="Numéro de version incrémenté à chaque modification (optimistic locking).",
        examples=[1, 5],
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
