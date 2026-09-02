from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import (
    PositiveFloat,
    PositiveInt,
    StringConstraints,
    field_validator,
    model_validator,
)

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
    base_url: str | None = None
    api_key: str | None = None
    timeout: PositiveFloat = 30.0
    normalize: bool = True
    multitenant: bool = False

    @model_validator(mode="before")
    @classmethod
    def apply_adapter_defaults(cls, values: Any) -> Any:
        if (
            isinstance(values, dict)
            and values.get("adapter") == "openai-compatible"
            and "normalize" not in values
        ):
            return {**values, "normalize": False}
        return values

    @field_validator("model_name")
    @classmethod
    def model_name_must_not_be_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("embedding model_name must not be empty")
        return normalized

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("embedding base_url must be a credential-free HTTP URL")
        if parsed.path in {"", "/"}:
            raise ValueError("embedding base_url must include the provider API prefix")
        return normalized

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_selected_adapter(self) -> "EmbeddingSettings":
        if self.adapter == "openai-compatible" and self.base_url is None:
            raise ValueError("embedding adapter openai-compatible requires base_url")
        return self
