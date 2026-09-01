from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    field_validator,
    model_validator,
)


class EmbeddingError(Exception):
    """Base error exposed by embedding adapters."""


class EmbeddingUnavailable(EmbeddingError):
    """Raised when the embedding provider is unavailable."""


class EmbeddingAuthenticationError(EmbeddingError):
    """Raised when provider credentials are rejected."""


class EmbeddingRateLimitError(EmbeddingError):
    """Raised when the provider rate-limits a request."""


class EmbeddingInvalidInput(EmbeddingError):
    """Raised before a provider call when an input batch is invalid."""


class EmbeddingDimensionMismatch(EmbeddingError):
    """Raised when provider vectors do not match the configured dimension."""


class _EmbeddingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EmbeddingText(_EmbeddingModel):
    """One provider-neutral text input, with an optional caller identifier."""

    id: str | None = None
    text: str

    @field_validator("text")
    @classmethod
    def text_must_not_be_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("embedding text must not be empty")
        return normalized


class EmbeddingResult(_EmbeddingModel):
    """One vector returned at the same index as its input text."""

    id: str | None = None
    index: NonNegativeInt
    vector: list[float] = Field(min_length=1)
    model_name: str
    dimensions: PositiveInt

    @field_validator("model_name")
    @classmethod
    def model_name_must_not_be_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("embedding model_name must not be empty")
        return normalized

    @model_validator(mode="after")
    def vector_must_match_dimensions(self) -> "EmbeddingResult":
        if len(self.vector) != self.dimensions:
            raise ValueError(
                "embedding vector length must match its declared dimensions"
            )
        return self


class EmbeddingUsage(_EmbeddingModel):
    """Optional provider usage metadata."""

    prompt_tokens: NonNegativeInt | None = None
    total_tokens: NonNegativeInt | None = None


class EmbeddingResponse(_EmbeddingModel):
    """Ordered, dimension-consistent response for one input batch."""

    results: list[EmbeddingResult] = Field(min_length=1)
    model_name: str
    dimensions: PositiveInt
    usage: EmbeddingUsage | None = None

    @field_validator("model_name")
    @classmethod
    def model_name_must_not_be_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("embedding model_name must not be empty")
        return normalized

    @model_validator(mode="after")
    def results_must_be_ordered_and_consistent(self) -> "EmbeddingResponse":
        actual_indices = [result.index for result in self.results]
        expected_indices = list(range(len(self.results)))
        if actual_indices != expected_indices:
            raise ValueError(
                "embedding result indices must preserve input order starting at zero"
            )
        if any(result.model_name != self.model_name for result in self.results):
            raise ValueError(
                "embedding result model_name must match the response model_name"
            )
        if any(result.dimensions != self.dimensions for result in self.results):
            raise ValueError(
                "embedding result dimensions must match the response dimensions"
            )
        return self


def validate_embedding_inputs(
    inputs: Sequence[EmbeddingText],
) -> tuple[EmbeddingText, ...]:
    """Materialize and validate a non-empty provider input batch."""
    validated = tuple(inputs)
    if not validated:
        raise EmbeddingInvalidInput("embedding inputs must not be empty")
    if any(not item.text.strip() for item in validated):
        raise EmbeddingInvalidInput("embedding text must not be empty")
    return validated


class EmbeddingPort(ABC):
    """Outbound port that computes vectors without persisting content."""

    @abstractmethod
    async def embed_texts(self, inputs: Sequence[EmbeddingText]) -> EmbeddingResponse:
        """Embed a non-empty text batch while preserving input order."""
        ...
