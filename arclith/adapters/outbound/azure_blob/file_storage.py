from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any

from arclith.adapters.outbound.azure_blob.client import (
    create_azure_blob_content_settings,
    safe_create_azure_blob_service_client,
)
from arclith.adapters.outbound.azure_blob.config import (
    AzureBlobStorageConfig,
    ResolvedAzureBlobConfig,
    normalize_optional_prefix,
    resolve_azure_blob_config,
)
from arclith.adapters.outbound.azure_blob.errors import (
    azure_blob_storage_error_from_provider,
    is_not_found_error,
)
from arclith.adapters.outbound.azure_blob.metadata import metadata_from_properties
from arclith.adapters.outbound.azure_blob.transfer import (
    has_readable_downloader,
    read_downloader,
    run_sync,
    spool_content,
)
from arclith.domain.ports.outbound.file_storage import (
    FileStorageError,
    FileStorageUnavailable,
    FileStoragePort,
    StoredObject,
    StoredObjectMetadata,
    StoredObjectStream,
    normalize_storage_key,
)


class AzureBlobFileStorage(FileStoragePort):
    """Azure Blob Storage implementation of the FileStoragePort contract."""

    def __init__(
        self,
        config: AzureBlobStorageConfig,
        *,
        client: Any | None = None,
        content_settings_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._config = config
        self._prefix = normalize_optional_prefix(config.prefix)
        self._injected_client = client
        self._default_client: Any | None = None
        self._content_settings_factory = content_settings_factory

    async def put(
        self,
        key: str,
        content: AsyncIterator[bytes],
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        normalized_key = normalize_storage_key(key)
        resolved = self._resolved_config(normalized_key)
        blob = self._blob_for(resolved, normalized_key)

        spooled = await spool_content(content)
        try:
            request: dict[str, Any] = {
                "overwrite": True,
                "length": spooled.size,
            }
            if metadata:
                request["metadata"] = dict(metadata)
            if content_type is not None:
                request["content_settings"] = self._content_settings_for(
                    content_type,
                    normalized_key,
                )

            await self._call_blob(
                "upload_blob",
                normalized_key,
                blob,
                spooled.body,
                **request,
            )
        finally:
            spooled.close()

        properties = await self._call_blob(
            "get_blob_properties",
            normalized_key,
            blob,
        )
        provider_metadata = metadata_from_properties(normalized_key, properties)
        return StoredObject(
            key=normalized_key,
            content_type=provider_metadata.content_type or content_type,
            size=provider_metadata.size
            if provider_metadata.size is not None
            else spooled.size,
            checksum=provider_metadata.checksum or spooled.checksum,
            etag=provider_metadata.etag,
            last_modified=provider_metadata.last_modified,
            custom=provider_metadata.custom or dict(metadata or {}),
        )

    async def get(self, key: str) -> StoredObjectStream:
        normalized_key = normalize_storage_key(key)
        resolved = self._resolved_config(normalized_key)
        blob = self._blob_for(resolved, normalized_key)
        properties = await self._call_blob(
            "get_blob_properties",
            normalized_key,
            blob,
        )
        downloader = await self._call_blob("download_blob", normalized_key, blob)
        if not has_readable_downloader(downloader):
            raise FileStorageUnavailable(
                "azure blob storage response body is unavailable", key=normalized_key
            )

        return StoredObjectStream(
            metadata=metadata_from_properties(normalized_key, properties),
            body=read_downloader(downloader, normalized_key),
        )

    async def delete(self, key: str) -> None:
        normalized_key = normalize_storage_key(key)
        resolved = self._resolved_config(normalized_key)
        blob = self._blob_for(resolved, normalized_key)
        await self._call_blob(
            "delete_blob",
            normalized_key,
            blob,
            not_found_ok=True,
        )

    async def exists(self, key: str) -> bool:
        normalized_key = normalize_storage_key(key)
        resolved = self._resolved_config(normalized_key)
        blob = self._blob_for(resolved, normalized_key)
        response = await self._call_blob(
            "exists",
            normalized_key,
            blob,
            not_found_ok=True,
        )
        return bool(response)

    async def stat(self, key: str) -> StoredObjectMetadata:
        normalized_key = normalize_storage_key(key)
        resolved = self._resolved_config(normalized_key)
        blob = self._blob_for(resolved, normalized_key)
        properties = await self._call_blob(
            "get_blob_properties",
            normalized_key,
            blob,
        )
        return metadata_from_properties(normalized_key, properties)

    async def _call_blob(
        self,
        operation: str,
        key: str,
        blob: Any,
        *args: Any,
        not_found_ok: bool = False,
        **kwargs: Any,
    ) -> Any:
        method = getattr(blob, operation)
        try:
            return await run_sync(method, *args, **kwargs)
        except Exception as e:
            if not_found_ok and is_not_found_error(e):
                return None
            raise azure_blob_storage_error_from_provider(e, key=key) from e

    def _blob_for(self, resolved: ResolvedAzureBlobConfig, normalized_key: str) -> Any:
        client = self._client_for(resolved, normalized_key)
        container_name = _require_container_name(resolved, normalized_key)
        try:
            return client.get_blob_client(
                container=container_name,
                blob=_object_key(normalized_key, resolved.prefix),
            )
        except Exception as e:
            raise azure_blob_storage_error_from_provider(e, key=normalized_key) from e

    def _client_for(self, resolved: ResolvedAzureBlobConfig, key: str) -> Any:
        if self._injected_client is not None:
            return self._injected_client
        if not self._config.multitenant:
            if self._default_client is None:
                self._default_client = safe_create_azure_blob_service_client(
                    resolved, key=key
                )
            return self._default_client
        return safe_create_azure_blob_service_client(resolved, key=key)

    def _resolved_config(self, key: str) -> ResolvedAzureBlobConfig:
        return resolve_azure_blob_config(self._config, base_prefix=self._prefix, key=key)

    def _content_settings_for(self, content_type: str, key: str) -> Any:
        factory = self._content_settings_factory or create_azure_blob_content_settings
        try:
            return factory(content_type)
        except FileStorageError as e:
            if e.key is None:
                e.key = key
            raise
        except Exception as e:
            raise azure_blob_storage_error_from_provider(e, key=key) from e


def _object_key(normalized_key: str, prefix: str) -> str:
    if not prefix:
        return normalized_key
    return f"{prefix}/{normalized_key}"


def _require_container_name(resolved: ResolvedAzureBlobConfig, key: str) -> str:
    if resolved.container_name is None:
        raise FileStorageUnavailable(
            "azure blob storage container_name is required", key=key
        )
    return resolved.container_name
