from __future__ import annotations

from typing import Annotated, Any, Literal
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
    dimensions: PositiveInt | None = None
    batch_size: PositiveInt = 64
    base_url: str | None = None
    api_key: str | None = None
    timeout: PositiveFloat = 30.0
    encoding_format: Literal["float"] = "float"
    normalize: bool = True
    multitenant: bool = False

    @model_validator(mode="before")
    @classmethod
    def apply_adapter_defaults(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        adapter = values.get("adapter")
        defaults: dict[str, Any] = {}
        if adapter in {"openai-compatible", "openai"} and "normalize" not in values:
            defaults["normalize"] = False
        if adapter == "openai" and (
            "base_url" not in values or values.get("base_url") is None
        ):
            defaults["base_url"] = "https://api.openai.com/v1"
        if defaults:
            return {**values, **defaults}
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
        if (
            self.adapter in {"deterministic", "openai-compatible"}
            and self.dimensions is None
        ):
            raise ValueError(f"embedding adapter {self.adapter} requires dimensions")
        return self
