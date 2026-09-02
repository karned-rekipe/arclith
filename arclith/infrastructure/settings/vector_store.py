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

VectorStoreAdapter = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
VectorDistance = Literal["cosine", "dot", "euclid"]


class VectorStoreSettings(SettingsModel):
    adapter: VectorStoreAdapter
    url: str | None = None
    api_key: str | None = None
    collection_name: str = "default"
    vector_size: PositiveInt
    distance: VectorDistance = "cosine"
    prefer_grpc: bool = False
    timeout: PositiveFloat = 5.0
    create_collection: bool = True
    multitenant: bool = False

    @model_validator(mode="before")
    @classmethod
    def apply_adapter_defaults(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        if values.get("adapter") == "qdrant" and values.get("url") is None:
            return {**values, "url": "http://localhost:6333"}
        return values

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
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
            raise ValueError("vector_store url must be a credential-free HTTP URL")
        return normalized

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("collection_name")
    @classmethod
    def collection_name_must_not_be_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("vector_store collection_name must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_selected_adapter(self) -> "VectorStoreSettings":
        if self.adapter == "memory" and self.multitenant:
            raise ValueError("vector_store adapter memory does not support multitenant")
        if self.adapter == "qdrant" and self.url is None:
            raise ValueError("vector_store adapter qdrant requires url")
        return self
