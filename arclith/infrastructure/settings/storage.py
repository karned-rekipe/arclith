from __future__ import annotations

from typing import Literal

from pydantic import field_validator, model_validator

from arclith.domain.ports.outbound.file_storage import (
    FileStorageInvalidKey,
    normalize_storage_key,
)
from arclith.infrastructure.settings._base import SettingsModel

StorageAdapter = Literal["filesystem", "s3", "azure-blob", "gcs"]


class StorageSettings(SettingsModel):
    adapter: StorageAdapter
    prefix: str = ""
    multitenant: bool = False
    root_path: str | None = None
    create_root: bool = True
    bucket_name: str | None = None
    region_name: str | None = None
    endpoint_url: str | None = None
    force_path_style: bool = False
    account_url: str | None = None
    container_name: str | None = None
    connection_string: str | None = None
    account_key: str | None = None
    sas_token: str | None = None
    use_default_credential: bool = False
    project_id: str | None = None
    credentials_path: str | None = None
    credentials_json: str | None = None
    credentials_json_b64: str | None = None

    @field_validator("prefix")
    @classmethod
    def must_be_valid_prefix(cls, v: str) -> str:
        if not v:
            return v
        try:
            return normalize_storage_key(v)
        except FileStorageInvalidKey as e:
            raise ValueError(str(e)) from e

    @model_validator(mode="after")
    def validate_selected_adapter_fields(self) -> "StorageSettings":
        if self.multitenant:
            return self

        required_fields_by_adapter: dict[StorageAdapter, tuple[str, ...]] = {
            "filesystem": ("root_path",),
            "s3": ("bucket_name",),
            "azure-blob": ("account_url", "container_name"),
            "gcs": ("bucket_name",),
        }
        missing = [
            field_name
            for field_name in required_fields_by_adapter[self.adapter]
            if not getattr(self, field_name)
        ]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"storage adapter {self.adapter} requires: {joined}")
        return self
