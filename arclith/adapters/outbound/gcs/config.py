from dataclasses import dataclass

from arclith.adapters.context import get_adapter_tenant_context
from arclith.domain.models.tenant import AdapterTenantCoords
from arclith.domain.ports.outbound.file_storage import normalize_storage_key


@dataclass(frozen=True)
class GCSStorageConfig:
    bucket_name: str | None = None
    prefix: str = ""
    project_id: str | None = None
    multitenant: bool = False


@dataclass(frozen=True)
class ResolvedGCSConfig:
    bucket_name: str | None
    prefix: str
    project_id: str | None
    credentials_path: str | None = None
    credentials_json: str | None = None
    credentials_json_b64: str | None = None


def normalize_optional_prefix(prefix: str) -> str:
    if not prefix:
        return ""
    return normalize_storage_key(prefix)


def resolve_gcs_config(
    config: GCSStorageConfig,
    *,
    base_prefix: str,
) -> ResolvedGCSConfig:
    base = ResolvedGCSConfig(
        bucket_name=_optional_text(config.bucket_name),
        prefix=base_prefix,
        project_id=_optional_text(config.project_id),
    )
    if not config.multitenant:
        return base

    coords = get_adapter_tenant_context("gcs")
    if coords is None:
        return base

    return ResolvedGCSConfig(
        bucket_name=_tenant_optional_text(coords, "bucket_name", base.bucket_name),
        prefix=_tenant_prefix(coords, base.prefix),
        project_id=_tenant_first_text(
            coords, ("project_id", "project"), base.project_id
        ),
        credentials_path=_tenant_first_text(
            coords,
            ("credentials_path", "service_account_file"),
            None,
        ),
        credentials_json=_tenant_first_text(
            coords,
            ("credentials_json", "service_account_json"),
            None,
        ),
        credentials_json_b64=_tenant_first_text(
            coords,
            ("credentials_json_b64", "service_account_json_b64"),
            None,
        ),
    )


def _tenant_prefix(coords: AdapterTenantCoords, fallback: str) -> str:
    if "prefix" not in coords.params:
        return fallback
    return normalize_optional_prefix(coords.params["prefix"])


def _tenant_optional_text(
    coords: AdapterTenantCoords,
    key: str,
    fallback: str | None,
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
