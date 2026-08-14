from dataclasses import dataclass

from arclith.adapters.context import get_adapter_tenant_context
from arclith.adapters.outbound.storage.config import (
    optional_text,
    tenant_bool,
    tenant_first_text,
    tenant_optional_text,
    tenant_prefix,
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


def resolve_azure_blob_config(
    config: AzureBlobStorageConfig,
    *,
    base_prefix: str,
    key: str,
) -> ResolvedAzureBlobConfig:
    base = ResolvedAzureBlobConfig(
        account_url=optional_text(config.account_url),
        container_name=optional_text(config.container_name),
        prefix=base_prefix,
        connection_string=optional_text(config.connection_string),
        account_key=optional_text(config.account_key),
        sas_token=optional_text(config.sas_token),
        use_default_credential=config.use_default_credential,
    )
    if not config.multitenant:
        return base

    coords = get_adapter_tenant_context("azure-blob")
    if coords is None:
        return base

    return ResolvedAzureBlobConfig(
        account_url=tenant_first_text(
            coords, ("account_url", "blob_service_url"), base.account_url
        ),
        container_name=tenant_first_text(
            coords, ("container_name", "container"), base.container_name
        ),
        prefix=tenant_prefix(coords, base.prefix),
        connection_string=tenant_first_text(
            coords, ("connection_string", "conn_str"), base.connection_string
        ),
        account_key=tenant_first_text(
            coords, ("account_key", "storage_account_key"), base.account_key
        ),
        sas_token=tenant_optional_text(coords, "sas_token", base.sas_token),
        use_default_credential=tenant_bool(
            coords,
            "use_default_credential",
            base.use_default_credential,
            key,
            adapter_label="azure blob",
            aliases=("default_credential", "managed_identity"),
        ),
    )
