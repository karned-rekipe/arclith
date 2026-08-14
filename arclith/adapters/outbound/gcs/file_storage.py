import asyncio
import hashlib
import tempfile
from collections.abc import AsyncIterator, Mapping
from typing import Any

from arclith.adapters.outbound.gcs.client import safe_create_gcs_client
from arclith.adapters.outbound.gcs.config import (
    GCSStorageConfig,
    ResolvedGCSConfig,
    normalize_optional_prefix,
    resolve_gcs_config,
)
from arclith.adapters.outbound.gcs.errors import (
    gcs_storage_error_from_provider,
    is_not_found_error,
    raise_gcs_storage_error,
)
from arclith.adapters.outbound.gcs.metadata import metadata_from_blob
from arclith.domain.ports.outbound.file_storage import (
    FileStorageUnavailable,
    FileStoragePort,
    StoredObject,
    StoredObjectMetadata,
    StoredObjectStream,
    normalize_storage_key,
)

_CHUNK_SIZE = 1024 * 1024
_SPOOL_MAX_SIZE = 8 * 1024 * 1024


class GCSFileStorage(FileStoragePort):
    """Google Cloud Storage implementation of the FileStoragePort contract."""

    def __init__(self, config: GCSStorageConfig, *, client: Any | None = None) -> None:
        self._config = config
        self._prefix = normalize_optional_prefix(config.prefix)
        self._injected_client = client
        self._default_client: Any | None = None

    async def put(
        self,
        key: str,
        content: AsyncIterator[bytes],
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        normalized_key = normalize_storage_key(key)
        resolved = self._resolved_config()
        blob = self._blob_for(resolved, normalized_key)

        digest = hashlib.sha256()
        size = 0
        buffer = tempfile.SpooledTemporaryFile(max_size=_SPOOL_MAX_SIZE)
        try:
            async for chunk in content:
                if not chunk:
                    continue
                digest.update(chunk)
                size += len(chunk)
                await asyncio.to_thread(buffer.write, chunk)
            await asyncio.to_thread(buffer.seek, 0)

            if metadata:
                blob.metadata = dict(metadata)

            await self._call_blob(
                "upload_from_file",
                normalized_key,
                blob,
                buffer,
                rewind=False,
                size=size,
                content_type=content_type,
            )
        finally:
            buffer.close()

        provider_metadata = metadata_from_blob(normalized_key, blob)
        return StoredObject(
            key=normalized_key,
            content_type=provider_metadata.content_type or content_type,
            size=provider_metadata.size if provider_metadata.size is not None else size,
            checksum=provider_metadata.checksum or f"sha256:{digest.hexdigest()}",
            etag=provider_metadata.etag,
            last_modified=provider_metadata.last_modified,
            custom=provider_metadata.custom or dict(metadata or {}),
        )

    async def get(self, key: str) -> StoredObjectStream:
        normalized_key = normalize_storage_key(key)
        resolved = self._resolved_config()
        blob = self._blob_for(resolved, normalized_key)
        await self._call_blob("reload", normalized_key, blob)
        body = await self._call_blob(
            "open",
            normalized_key,
            blob,
            "rb",
            chunk_size=_CHUNK_SIZE,
        )
        if body is None or not hasattr(body, "read"):
            raise FileStorageUnavailable(
                "gcs storage response body is unavailable", key=normalized_key
            )

        return StoredObjectStream(
            metadata=metadata_from_blob(normalized_key, blob),
            body=self._read_body(body, normalized_key),
        )

    async def delete(self, key: str) -> None:
        normalized_key = normalize_storage_key(key)
        resolved = self._resolved_config()
        blob = self._blob_for(resolved, normalized_key)
        await self._call_blob("delete", normalized_key, blob, not_found_ok=True)

    async def exists(self, key: str) -> bool:
        normalized_key = normalize_storage_key(key)
        resolved = self._resolved_config()
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
        resolved = self._resolved_config()
        blob = self._blob_for(resolved, normalized_key)
        await self._call_blob("reload", normalized_key, blob)
        return metadata_from_blob(normalized_key, blob)

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
            return await asyncio.to_thread(method, *args, **kwargs)
        except Exception as e:
            if not_found_ok and is_not_found_error(e):
                return None
            raise gcs_storage_error_from_provider(e, key=key) from e

    async def _read_body(self, body: Any, key: str) -> AsyncIterator[bytes]:
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, _CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        except Exception as e:
            raise_gcs_storage_error(e, key=key)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                await asyncio.to_thread(close)

    def _blob_for(self, resolved: ResolvedGCSConfig, normalized_key: str) -> Any:
        bucket = self._bucket_for(resolved, normalized_key)
        return bucket.blob(_object_key(normalized_key, resolved.prefix))

    def _bucket_for(self, resolved: ResolvedGCSConfig, key: str) -> Any:
        client = self._client_for(resolved, key)
        return client.bucket(_require_bucket_name(resolved, key))

    def _client_for(self, resolved: ResolvedGCSConfig, key: str) -> Any:
        if self._injected_client is not None:
            return self._injected_client
        if not self._config.multitenant:
            if self._default_client is None:
                self._default_client = safe_create_gcs_client(resolved, key=key)
            return self._default_client
        return safe_create_gcs_client(resolved, key=key)

    def _resolved_config(self) -> ResolvedGCSConfig:
        return resolve_gcs_config(self._config, base_prefix=self._prefix)


def _object_key(normalized_key: str, prefix: str) -> str:
    if not prefix:
        return normalized_key
    return f"{prefix}/{normalized_key}"


def _require_bucket_name(resolved: ResolvedGCSConfig, key: str) -> str:
    if resolved.bucket_name is None:
        raise FileStorageUnavailable("gcs storage bucket_name is required", key=key)
    return resolved.bucket_name
