from __future__ import annotations

from typing import Annotated, Literal

from pydantic import PositiveInt, StringConstraints, field_validator, model_validator

from arclith.infrastructure.settings._base import SettingsModel

VectorStoreAdapter = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
VectorDistance = Literal["cosine", "dot", "euclid"]


class VectorStoreSettings(SettingsModel):
    adapter: VectorStoreAdapter
    collection_name: str = "default"
    vector_size: PositiveInt
    distance: VectorDistance = "cosine"
    multitenant: bool = False

    @field_validator("collection_name")
    @classmethod
    def collection_name_must_not_be_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("vector_store collection_name must not be empty")
        return normalized

    @model_validator(mode="after")
    def reject_unsupported_memory_multitenancy(self) -> "VectorStoreSettings":
        if self.adapter == "memory" and self.multitenant:
            raise ValueError("vector_store adapter memory does not support multitenant")
        return self
