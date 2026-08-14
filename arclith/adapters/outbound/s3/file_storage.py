import asyncio
import hashlib
import tempfile
from collections.abc import AsyncIterator, Mapping
from typing import Any

from arclith.adapters.outbound.s3.client import safe_create_s3_client
from arclith.adapters.outbound.s3.config import (
    ResolvedS3Config,
    S3StorageConfig,
    normalize_optional_prefix,
    resolve_s3_config,
)
from arclith.adapters.outbound.s3.errors import (
    is_not_found_error,
    raise_s3_storage_error,
    s3_storage_error_from_provider,
)
from arclith.adapters.outbound.s3.metadata import (
    clean_etag,
    metadata_from_response,
    response_string,
    response_value,
)
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


class S3FileStorage(FileStoragePort):
    """AWS S3 compatible implementation of the FileStoragePort contract."""

    def __init__(self, config: S3StorageConfig, *, client: Any | None = None) -> None:
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
        resolved = self._resolved_config(normalized_key)
        bucket_name = _require_bucket_name(resolved, normalized_key)
        object_key = _object_key(normalized_key, resolved.prefix)

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

            request: dict[str, Any] = {
                "Bucket": bucket_name,
                "Key": object_key,
                "Body": buffer,
            }
            if content_type is not None:
                request["ContentType"] = content_type
            if metadata:
                request["Metadata"] = dict(metadata)

            response = await self._call_client(
                "put_object", normalized_key, resolved, **request
            )
        finally:
            buffer.close()

        checksum = f"sha256:{digest.hexdigest()}"
        return StoredObject(
            key=normalized_key,
            content_type=content_type,
            size=size,
            checksum=checksum,
            etag=clean_etag(response_string(response, "ETag")),
            custom=dict(metadata or {}),
        )

    async def get(self, key: str) -> StoredObjectStream:
        normalized_key = normalize_storage_key(key)
        resolved = self._resolved_config(normalized_key)
        response = await self._call_client(
            "get_object",
            normalized_key,
            resolved,
            Bucket=_require_bucket_name(resolved, normalized_key),
            Key=_object_key(normalized_key, resolved.prefix),
        )
        body = response_value(response, "Body")
        if body is None or not hasattr(body, "read"):
            raise FileStorageUnavailable(
                "s3 storage response body is unavailable", key=normalized_key
            )

        return StoredObjectStream(
            metadata=metadata_from_response(normalized_key, response),
            body=self._read_body(body, normalized_key),
        )

    async def delete(self, key: str) -> None:
        normalized_key = normalize_storage_key(key)
        resolved = self._resolved_config(normalized_key)
        await self._call_client(
            "delete_object",
            normalized_key,
            resolved,
            not_found_ok=True,
            Bucket=_require_bucket_name(resolved, normalized_key),
            Key=_object_key(normalized_key, resolved.prefix),
        )

    async def exists(self, key: str) -> bool:
        normalized_key = normalize_storage_key(key)
        resolved = self._resolved_config(normalized_key)
        response = await self._call_client(
            "head_object",
            normalized_key,
            resolved,
            not_found_ok=True,
            Bucket=_require_bucket_name(resolved, normalized_key),
            Key=_object_key(normalized_key, resolved.prefix),
        )
        return response is not None

    async def stat(self, key: str) -> StoredObjectMetadata:
        normalized_key = normalize_storage_key(key)
        resolved = self._resolved_config(normalized_key)
        response = await self._call_client(
            "head_object",
            normalized_key,
            resolved,
            Bucket=_require_bucket_name(resolved, normalized_key),
            Key=_object_key(normalized_key, resolved.prefix),
        )
        return metadata_from_response(normalized_key, response)

    async def _call_client(
        self,
        operation: str,
        key: str,
        resolved: ResolvedS3Config,
        *,
        not_found_ok: bool = False,
        **kwargs: Any,
    ) -> Any:
        client = self._client_for(resolved, key)
        method = getattr(client, operation)
        try:
            return await asyncio.to_thread(method, **kwargs)
        except Exception as e:
            if not_found_ok and is_not_found_error(e):
                return None
            raise s3_storage_error_from_provider(e, key=key) from e

    async def _read_body(self, body: Any, key: str) -> AsyncIterator[bytes]:
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, _CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        except Exception as e:
            raise_s3_storage_error(e, key=key)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                await asyncio.to_thread(close)

    def _client_for(self, resolved: ResolvedS3Config, key: str) -> Any:
        if self._injected_client is not None:
            return self._injected_client
        if not self._config.multitenant:
            if self._default_client is None:
                self._default_client = safe_create_s3_client(resolved, key=key)
            return self._default_client
        return safe_create_s3_client(resolved, key=key)

    def _resolved_config(self, key: str) -> ResolvedS3Config:
        return resolve_s3_config(self._config, base_prefix=self._prefix, key=key)


def _object_key(normalized_key: str, prefix: str) -> str:
    if not prefix:
        return normalized_key
    return f"{prefix}/{normalized_key}"


def _require_bucket_name(resolved: ResolvedS3Config, key: str) -> str:
    if resolved.bucket_name is None:
        raise FileStorageUnavailable("s3 storage bucket_name is required", key=key)
    return resolved.bucket_name
