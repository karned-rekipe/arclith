from __future__ import annotations

from typing import Literal

from pydantic import PositiveInt, field_validator

from arclith.infrastructure.settings._base import SettingsModel

EmbeddingAdapter = Literal["deterministic"]


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
