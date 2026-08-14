from dataclasses import dataclass

from arclith.adapters.context import get_adapter_tenant_context
from arclith.adapters.outbound.storage.config import (
    optional_text,
    tenant_first_text,
    tenant_optional_text,
    tenant_prefix,
)


@dataclass(frozen=True)
class GCSStorageConfig:
    bucket_name: str | None = None
    prefix: str = ""
    project_id: str | None = None
    credentials_path: str | None = None
    credentials_json: str | None = None
    credentials_json_b64: str | None = None
    multitenant: bool = False


@dataclass(frozen=True)
class ResolvedGCSConfig:
    bucket_name: str | None
    prefix: str
    project_id: str | None
    credentials_path: str | None = None
    credentials_json: str | None = None
    credentials_json_b64: str | None = None


def resolve_gcs_config(
    config: GCSStorageConfig,
    *,
    base_prefix: str,
) -> ResolvedGCSConfig:
    base = ResolvedGCSConfig(
        bucket_name=optional_text(config.bucket_name),
        prefix=base_prefix,
        project_id=optional_text(config.project_id),
        credentials_path=optional_text(config.credentials_path),
        credentials_json=optional_text(config.credentials_json),
        credentials_json_b64=optional_text(config.credentials_json_b64),
    )
    if not config.multitenant:
        return base

    coords = get_adapter_tenant_context("gcs")
    if coords is None:
        return base

    return ResolvedGCSConfig(
        bucket_name=tenant_optional_text(coords, "bucket_name", base.bucket_name),
        prefix=tenant_prefix(coords, base.prefix),
        project_id=tenant_first_text(
            coords, ("project_id", "project"), base.project_id
        ),
        credentials_path=tenant_first_text(
            coords,
            ("credentials_path", "service_account_file"),
            base.credentials_path,
        ),
        credentials_json=tenant_first_text(
            coords,
            ("credentials_json", "service_account_json"),
            base.credentials_json,
        ),
        credentials_json_b64=tenant_first_text(
            coords,
            ("credentials_json_b64", "service_account_json_b64"),
            base.credentials_json_b64,
        ),
    )
