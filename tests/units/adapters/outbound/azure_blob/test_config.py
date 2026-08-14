import pytest

from arclith.adapters.context import set_tenant_context
from arclith.adapters.outbound.azure_blob.config import (
    AzureBlobStorageConfig,
    normalize_optional_prefix,
    resolve_azure_blob_config,
)
from arclith.domain.models.tenant import AdapterTenantCoords, TenantContext
from arclith.domain.ports.outbound.file_storage import FileStorageUnavailable


def test_resolve_azure_blob_config_uses_single_tenant_values() -> None:
    resolved = resolve_azure_blob_config(
        AzureBlobStorageConfig(
            account_url=" https://account.blob.core.windows.net ",
            container_name=" arclith-files ",
            prefix="unused",
            connection_string=" UseDevelopmentStorage=true ",
            account_key=" account-key ",
            sas_token=" ?token ",
            use_default_credential=True,
        ),
        base_prefix="uploads",
        key="docs/readme.txt",
    )

    assert resolved.account_url == "https://account.blob.core.windows.net"
    assert resolved.container_name == "arclith-files"
    assert resolved.prefix == "uploads"
    assert resolved.connection_string == "UseDevelopmentStorage=true"
    assert resolved.account_key == "account-key"
    assert resolved.sas_token == "?token"
    assert resolved.use_default_credential is True


def test_resolve_azure_blob_config_accepts_tenant_aliases() -> None:
    token = set_tenant_context(
        TenantContext(
            adapters={
                "azure-blob": AdapterTenantCoords(
                    params={
                        "blob_service_url": "https://tenant.blob.core.windows.net",
                        "container": "tenant-container",
                        "prefix": "tenant/uploads",
                        "conn_str": "UseDevelopmentStorage=true",
                        "storage_account_key": "tenant-key",
                        "sas_token": "?tenant-sas",
                        "managed_identity": "true",
                    }
                )
            }
        )
    )
    try:
        resolved = resolve_azure_blob_config(
            AzureBlobStorageConfig(
                account_url="https://fallback.blob.core.windows.net",
                container_name="fallback-container",
                prefix="fallback",
                multitenant=True,
            ),
            base_prefix="fallback",
            key="docs/readme.txt",
        )
    finally:
        token.var.reset(token)

    assert resolved.account_url == "https://tenant.blob.core.windows.net"
    assert resolved.container_name == "tenant-container"
    assert resolved.prefix == "tenant/uploads"
    assert resolved.connection_string == "UseDevelopmentStorage=true"
    assert resolved.account_key == "tenant-key"
    assert resolved.sas_token == "?tenant-sas"
    assert resolved.use_default_credential is True


def test_resolve_azure_blob_config_rejects_invalid_tenant_bool() -> None:
    token = set_tenant_context(
        TenantContext(
            adapters={
                "azure-blob": AdapterTenantCoords(
                    params={"use_default_credential": "sometimes"}
                )
            }
        )
    )
    try:
        with pytest.raises(FileStorageUnavailable, match="must be boolean"):
            resolve_azure_blob_config(
                AzureBlobStorageConfig(multitenant=True),
                base_prefix="",
                key="docs/readme.txt",
            )
    finally:
        token.var.reset(token)


def test_normalize_optional_prefix_accepts_empty_prefix() -> None:
    assert normalize_optional_prefix("") == ""
