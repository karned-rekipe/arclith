from dataclasses import dataclass

from arclith.adapters.context import get_adapter_tenant_context
from arclith.domain.models.tenant import AdapterTenantCoords
from arclith.domain.ports.outbound.file_storage import (
    FileStorageUnavailable,
    normalize_storage_key,
)


@dataclass(frozen=True)
class S3StorageConfig:
    bucket_name: str | None = None
    prefix: str = ""
    region_name: str | None = None
    endpoint_url: str | None = None
    force_path_style: bool = False
    multitenant: bool = False


@dataclass(frozen=True)
class ResolvedS3Config:
    bucket_name: str | None
    prefix: str
    region_name: str | None
    endpoint_url: str | None
    force_path_style: bool
    profile_name: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None


def normalize_optional_prefix(prefix: str) -> str:
    if not prefix:
        return ""
    return normalize_storage_key(prefix)


def resolve_s3_config(
    config: S3StorageConfig,
    *,
    base_prefix: str,
    key: str,
) -> ResolvedS3Config:
    base = ResolvedS3Config(
        bucket_name=_optional_text(config.bucket_name),
        prefix=base_prefix,
        region_name=_optional_text(config.region_name),
        endpoint_url=_optional_text(config.endpoint_url),
        force_path_style=config.force_path_style,
    )
    if not config.multitenant:
        return base

    coords = get_adapter_tenant_context("s3")
    if coords is None:
        return base

    return ResolvedS3Config(
        bucket_name=_tenant_optional_text(coords, "bucket_name", base.bucket_name),
        prefix=_tenant_prefix(coords, base.prefix),
        region_name=_tenant_first_text(
            coords, ("region_name", "region"), base.region_name
        ),
        endpoint_url=_tenant_optional_text(coords, "endpoint_url", base.endpoint_url),
        force_path_style=_tenant_bool(
            coords, "force_path_style", base.force_path_style, key
        ),
        profile_name=_tenant_optional_text(coords, "profile_name", None),
        aws_access_key_id=_tenant_first_text(
            coords, ("aws_access_key_id", "access_key_id"), None
        ),
        aws_secret_access_key=_tenant_first_text(
            coords,
            ("aws_secret_access_key", "secret_access_key"),
            None,
        ),
        aws_session_token=_tenant_first_text(
            coords, ("aws_session_token", "session_token"), None
        ),
    )


def _tenant_prefix(coords: AdapterTenantCoords, fallback: str) -> str:
    if "prefix" not in coords.params:
        return fallback
    return normalize_optional_prefix(coords.params["prefix"])


def _tenant_optional_text(
    coords: AdapterTenantCoords, key: str, fallback: str | None
) -> str | None:
    if key not in coords.params:
        return fallback
    return _optional_text(coords.params[key])


def _tenant_first_text(
    coords: AdapterTenantCoords,
    keys: tuple[str, ...],
    fallback: str | None,
) -> str | None:
    for key in keys:
        if key in coords.params:
            return _optional_text(coords.params[key])
    return fallback


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _tenant_bool(
    coords: AdapterTenantCoords, field: str, fallback: bool, key: str
) -> bool:
    if field not in coords.params:
        return fallback
    normalized = coords.params[field].strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise FileStorageUnavailable(
        f"s3 storage tenant field {field} must be boolean", key=key
    )
