from dataclasses import dataclass

from arclith.adapters.context import get_adapter_tenant_context
from arclith.domain.models.tenant import AdapterTenantCoords
from arclith.domain.ports.outbound.file_storage import (
    FileStorageUnavailable,
    normalize_storage_key,
)


@dataclass(frozen=True)
class AzureBlobStorageConfig:
    account_url: str | None = None
    container_name: str | None = None
    prefix: str = ""
    connection_string: str | None = None
    account_key: str | None = None
    sas_token: str | None = None
    use_default_credential: bool = False
    multitenant: bool = False


@dataclass(frozen=True)
class ResolvedAzureBlobConfig:
    account_url: str | None
    container_name: str | None
    prefix: str
    connection_string: str | None = None
    account_key: str | None = None
    sas_token: str | None = None
    use_default_credential: bool = False


def normalize_optional_prefix(prefix: str) -> str:
    if not prefix:
        return ""
    return normalize_storage_key(prefix)


def resolve_azure_blob_config(
    config: AzureBlobStorageConfig,
    *,
    base_prefix: str,
    key: str,
) -> ResolvedAzureBlobConfig:
    base = ResolvedAzureBlobConfig(
        account_url=_optional_text(config.account_url),
        container_name=_optional_text(config.container_name),
        prefix=base_prefix,
        connection_string=_optional_text(config.connection_string),
        account_key=_optional_text(config.account_key),
        sas_token=_optional_text(config.sas_token),
        use_default_credential=config.use_default_credential,
    )
    if not config.multitenant:
        return base

    coords = get_adapter_tenant_context("azure-blob")
    if coords is None:
        return base

    return ResolvedAzureBlobConfig(
        account_url=_tenant_first_text(
            coords, ("account_url", "blob_service_url"), base.account_url
        ),
        container_name=_tenant_first_text(
            coords, ("container_name", "container"), base.container_name
        ),
        prefix=_tenant_prefix(coords, base.prefix),
        connection_string=_tenant_first_text(
            coords, ("connection_string", "conn_str"), base.connection_string
        ),
        account_key=_tenant_first_text(
            coords, ("account_key", "storage_account_key"), base.account_key
        ),
        sas_token=_tenant_optional_text(coords, "sas_token", base.sas_token),
        use_default_credential=_tenant_bool(
            coords,
            "use_default_credential",
            base.use_default_credential,
            key,
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


def _tenant_bool(
    coords: AdapterTenantCoords, field: str, fallback: bool, key: str
) -> bool:
    value = _tenant_first_text(
        coords,
        (field, "default_credential", "managed_identity"),
        None,
    )
    if value is None:
        return fallback
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise FileStorageUnavailable(
        f"azure blob storage tenant field {field} must be boolean", key=key
    )


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped
