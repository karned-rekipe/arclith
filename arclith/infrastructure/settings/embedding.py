from __future__ import annotations

from typing import Annotated

from pydantic import PositiveInt, StringConstraints, field_validator

from arclith.infrastructure.settings._base import SettingsModel

EmbeddingAdapter = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class EmbeddingSettings(SettingsModel):
    adapter: EmbeddingAdapter
    model_name: str
    dimensions: PositiveInt
    batch_size: PositiveInt = 64
    normalize: bool = True
    multitenant: bool = False

    @field_validator("model_name")
    @classmethod
    def model_name_must_not_be_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("embedding model_name must not be empty")
        return normalized
