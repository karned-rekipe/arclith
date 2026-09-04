from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PositiveInt,
    field_validator,
)

from arclith.domain.models.json import validate_finite_json


class VectorStoreError(Exception):
    """Base error exposed by vector-store adapters."""


class VectorStoreUnavailable(VectorStoreError):
    """Raised when the vector backend is unavailable."""


class VectorStoreCollectionNotFound(VectorStoreError):
    """Raised when the configured collection does not exist."""


class VectorStoreDimensionMismatch(VectorStoreError):
    """Raised when a vector does not match the configured dimension."""


class VectorStorePermissionDenied(VectorStoreError):
    """Raised when backend credentials or policy reject an operation."""


class VectorStoreInvalidPayload(VectorStoreError):
    """Raised when a payload cannot be represented as JSON."""


class _VectorStoreModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _VectorModel(_VectorStoreModel):
    vector: list[float] = Field(min_length=1)

    @field_validator("vector")
    @classmethod
    def vector_must_contain_finite_values(cls, value: list[float]) -> list[float]:
        if any(not math.isfinite(component) for component in value):
            raise ValueError("vector values must be finite")
        return value


class VectorPoint(_VectorModel):
    """Provider-neutral vector and its JSON search projection."""

    id: str
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def id_must_not_be_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("vector point id must not be empty")
        return normalized

    @field_validator("payload")
    @classmethod
    def payload_must_be_strict_json(
        cls, value: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        validate_finite_json(value)
        return value


class VectorSearchQuery(_VectorModel):
    """Dense-vector search with exact-match payload filters."""

    limit: PositiveInt = 10
    filters: dict[str, JsonValue] = Field(default_factory=dict)
    score_threshold: float | None = None
    include_payload: bool = True
    include_vector: bool = False

    @field_validator("filters")
    @classmethod
    def filters_must_be_strict_json(
        cls, value: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        validate_finite_json(value)
        return value

    @field_validator("score_threshold")
    @classmethod
    def score_threshold_must_be_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("vector search score_threshold must be finite")
        return value


class VectorSearchHit(_VectorStoreModel):
    """One backend-independent nearest-neighbour result."""

    id: str
    score: float
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    vector: list[float] | None = None

    @field_validator("id")
    @classmethod
    def id_must_not_be_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("vector search hit id must not be empty")
        return normalized

    @field_validator("payload")
    @classmethod
    def payload_must_be_strict_json(
        cls, value: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        validate_finite_json(value)
        return value

    @field_validator("score")
    @classmethod
    def score_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("vector search score must be finite")
        return value

    @field_validator("vector")
    @classmethod
    def optional_vector_must_be_finite(
        cls, value: list[float] | None
    ) -> list[float] | None:
        if value == []:
            raise ValueError("vector search hit vector must not be empty")
        if value is not None and any(
            not math.isfinite(component) for component in value
        ):
            raise ValueError("vector values must be finite")
        return value


class VectorStorePort(ABC):
    """Outbound port for a rebuildable dense-vector search index."""

    async def close(self) -> None:
        """Release owned provider resources; no-op for adapters without clients."""

        return None

    @abstractmethod
    async def ensure_collection(self) -> None:
        """Create the configured logical collection when it is absent."""
        pass  # pragma: no cover

    @abstractmethod
    async def upsert(self, points: Sequence[VectorPoint]) -> None:
        """Insert or replace points by their provider-neutral string ID."""
        pass  # pragma: no cover

    @abstractmethod
    async def delete(self, ids: Sequence[str]) -> None:
        """Delete point IDs; unknown IDs are ignored."""
        pass  # pragma: no cover

    @abstractmethod
    async def search(self, query: VectorSearchQuery) -> list[VectorSearchHit]:
        """Return best-first hits for one dense vector query."""
        pass  # pragma: no cover
