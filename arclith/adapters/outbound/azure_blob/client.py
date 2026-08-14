from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from arclith.adapters.outbound.azure_blob.config import ResolvedAzureBlobConfig
from arclith.adapters.outbound.azure_blob.errors import raise_azure_blob_storage_error
from arclith.domain.ports.outbound.file_storage import (
    FileStorageError,
    FileStorageUnavailable,
)


def safe_create_azure_blob_service_client(
    resolved: ResolvedAzureBlobConfig,
    *,
    key: str,
) -> Any:
    try:
        return create_azure_blob_service_client(resolved)
    except FileStorageError as e:
        if e.key is None:
            e.key = key
        raise
    except Exception as e:
        raise_azure_blob_storage_error(e, key=key)


def create_azure_blob_service_client(resolved: ResolvedAzureBlobConfig) -> Any:
    modules = _import_azure_modules()
    _reject_ambiguous_credentials(resolved)

    if resolved.connection_string is not None:
        return modules["BlobServiceClient"].from_connection_string(
            conn_str=resolved.connection_string
        )

    if resolved.account_url is None:
        raise FileStorageUnavailable("azure blob storage account_url is required")

    credential = _credential_from_config(resolved, modules)
    return modules["BlobServiceClient"](
        account_url=resolved.account_url,
        credential=credential,
    )


def create_azure_blob_content_settings(content_type: str) -> Any:
    modules = _import_azure_modules()
    return modules["ContentSettings"](content_type=content_type)


def _import_azure_modules() -> dict[str, Any]:
    try:
        from azure.core.credentials import AzureNamedKeyCredential, AzureSasCredential
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient, ContentSettings
    except ImportError as e:
        raise FileStorageUnavailable(
            "azure blob storage requires optional dependency arclith[azure-blob]"
        ) from e

    return {
        "AzureNamedKeyCredential": AzureNamedKeyCredential,
        "AzureSasCredential": AzureSasCredential,
        "BlobServiceClient": BlobServiceClient,
        "ContentSettings": ContentSettings,
        "DefaultAzureCredential": DefaultAzureCredential,
    }


def _credential_from_config(
    resolved: ResolvedAzureBlobConfig,
    modules: Mapping[str, Any],
) -> Any | None:
    if resolved.account_key is not None:
        account_name = _account_name_from_url(resolved.account_url)
        if account_name is None:
            raise FileStorageUnavailable(
                "azure blob storage account_url is required for account_key"
            )
        return modules["AzureNamedKeyCredential"](
            name=account_name,
            key=resolved.account_key,
        )
    if resolved.sas_token is not None:
        return modules["AzureSasCredential"](resolved.sas_token.lstrip("?"))
    if resolved.use_default_credential:
        return modules["DefaultAzureCredential"]()
    return None


def _reject_ambiguous_credentials(resolved: ResolvedAzureBlobConfig) -> None:
    configured = [
        resolved.connection_string is not None,
        resolved.account_key is not None,
        resolved.sas_token is not None,
        resolved.use_default_credential,
    ]
    if sum(configured) > 1:
        raise FileStorageUnavailable("azure blob storage credentials are ambiguous")


def _account_name_from_url(account_url: str | None) -> str | None:
    if account_url is None:
        return None
    hostname = urlsplit(account_url).hostname
    if hostname is None:
        return None
    account_name = hostname.split(".", maxsplit=1)[0].strip()
    if not account_name:
        return None
    return account_name
