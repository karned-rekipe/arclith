import asyncio
import hashlib
import tempfile
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NoReturn

from arclith.adapters.context import get_adapter_tenant_context
from arclith.domain.models.tenant import AdapterTenantCoords
from arclith.domain.ports.outbound.file_storage import (
    FileStorageConflict,
    FileStorageError,
    FileStorageNotFound,
    FileStoragePermissionDenied,
    FileStoragePort,
    FileStorageUnavailable,
    StoredObject,
    StoredObjectMetadata,
    StoredObjectStream,
    normalize_storage_key,
)

_CHUNK_SIZE = 1024 * 1024
_SPOOL_MAX_SIZE = 8 * 1024 * 1024
_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound", "Not Found"})
_PERMISSION_CODES = frozenset({
    "403",
    "AccessDenied",
    "AllAccessDisabled",
    "ExpiredToken",
    "InvalidAccessKeyId",
    "InvalidToken",
    "SignatureDoesNotMatch",
})
_PERMISSION_ERROR_NAMES = frozenset({
    "CredentialRetrievalError",
    "NoCredentialsError",
    "PartialCredentialsError",
    "ProfileNotFound",
    "SSOTokenLoadError",
    "UnauthorizedSSOTokenError",
})
_CONFLICT_CODES = frozenset({
    "ConditionalRequestConflict",
    "OperationAborted",
    "PreconditionFailed",
})
_UNAVAILABLE_CODES = frozenset({
    "InternalError",
    "NoSuchBucket",
    "RequestTimeout",
    "ServiceUnavailable",
    "SlowDown",
    "Throttling",
    "ThrottlingException",
})
_UNAVAILABLE_ERROR_NAMES = frozenset({
    "ConnectTimeoutError",
    "ConnectionClosedError",
    "EndpointConnectionError",
    "ReadTimeoutError",
})


@dataclass(frozen=True)
class S3StorageConfig:
    bucket_name: str | None = None
    prefix: str = ""
    region_name: str | None = None
    endpoint_url: str | None = None
    force_path_style: bool = False
    multitenant: bool = False


@dataclass(frozen=True)
class _ResolvedS3Config:
    bucket_name: str | None
    prefix: str
    region_name: str | None
    endpoint_url: str | None
    force_path_style: bool
    profile_name: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None


class S3FileStorage(FileStoragePort):
    """AWS S3 compatible implementation of the FileStoragePort contract."""

    def __init__(self, config: S3StorageConfig, *, client: Any | None = None) -> None:
        self._config = config
        self._prefix = _normalize_optional_prefix(config.prefix)
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

            response = await self._call_client("put_object", normalized_key, resolved, **request)
        finally:
            buffer.close()

        checksum = f"sha256:{digest.hexdigest()}"
        return StoredObject(
            key=normalized_key,
            content_type=content_type,
            size=size,
            checksum=checksum,
            etag=_clean_etag(_response_string(response, "ETag")),
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
        body = _response_value(response, "Body")
        if body is None or not hasattr(body, "read"):
            raise FileStorageUnavailable("s3 storage response body is unavailable", key=normalized_key)

        return StoredObjectStream(
            metadata=_metadata_from_response(normalized_key, response),
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
        return _metadata_from_response(normalized_key, response)

    async def _call_client(
        self,
        operation: str,
        key: str,
        resolved: _ResolvedS3Config,
        *,
        not_found_ok: bool = False,
        **kwargs: Any,
    ) -> Any:
        client = self._client_for(resolved, key)
        method = getattr(client, operation)
        try:
            return await asyncio.to_thread(method, **kwargs)
        except Exception as e:
            if not_found_ok and _is_not_found_error(e):
                return None
            _raise_s3_storage_error(e, key=key)

    async def _read_body(self, body: Any, key: str) -> AsyncIterator[bytes]:
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, _CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        except Exception as e:
            _raise_s3_storage_error(e, key=key)
        finally:
            close = getattr(body, "close", None)
            if close is not None:
                await asyncio.to_thread(close)

    def _client_for(self, resolved: _ResolvedS3Config, key: str) -> Any:
        if self._injected_client is not None:
            return self._injected_client
        if not self._config.multitenant:
            if self._default_client is None:
                self._default_client = _safe_create_s3_client(resolved, key)
            return self._default_client
        return _safe_create_s3_client(resolved, key)

    def _resolved_config(self, key: str) -> _ResolvedS3Config:
        base = _ResolvedS3Config(
            bucket_name=_optional_text(self._config.bucket_name),
            prefix=self._prefix,
            region_name=_optional_text(self._config.region_name),
            endpoint_url=_optional_text(self._config.endpoint_url),
            force_path_style=self._config.force_path_style,
        )
        if not self._config.multitenant:
            return base

        coords = get_adapter_tenant_context("s3")
        if coords is None:
            return base

        return _ResolvedS3Config(
            bucket_name=_tenant_optional_text(coords, "bucket_name", base.bucket_name),
            prefix=_tenant_prefix(coords, base.prefix),
            region_name=_tenant_first_text(coords, ("region_name", "region"), base.region_name),
            endpoint_url=_tenant_optional_text(coords, "endpoint_url", base.endpoint_url),
            force_path_style=_tenant_bool(coords, "force_path_style", base.force_path_style, key),
            profile_name=_tenant_optional_text(coords, "profile_name", None),
            aws_access_key_id=_tenant_first_text(coords, ("aws_access_key_id", "access_key_id"), None),
            aws_secret_access_key=_tenant_first_text(
                coords,
                ("aws_secret_access_key", "secret_access_key"),
                None,
            ),
            aws_session_token=_tenant_first_text(coords, ("aws_session_token", "session_token"), None),
        )


def _safe_create_s3_client(resolved: _ResolvedS3Config, key: str) -> Any:
    try:
        return _create_s3_client(resolved)
    except FileStorageError:
        raise
    except Exception as e:
        _raise_s3_storage_error(e, key=key)


def _create_s3_client(resolved: _ResolvedS3Config) -> Any:
    try:
        import boto3
        from botocore.config import Config
    except ImportError as e:
        raise FileStorageUnavailable("s3 storage requires optional dependency arclith[s3]") from e

    session_kwargs = _without_none({
        "profile_name": resolved.profile_name,
        "region_name": resolved.region_name,
        "aws_access_key_id": resolved.aws_access_key_id,
        "aws_secret_access_key": resolved.aws_secret_access_key,
        "aws_session_token": resolved.aws_session_token,
    })
    client_kwargs = _without_none({"endpoint_url": resolved.endpoint_url})
    if resolved.force_path_style:
        client_kwargs["config"] = Config(s3={"addressing_style": "path"})

    session = boto3.Session(**session_kwargs)
    return session.client("s3", **client_kwargs)


def _without_none(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _normalize_optional_prefix(prefix: str) -> str:
    if not prefix:
        return ""
    return normalize_storage_key(prefix)


def _object_key(normalized_key: str, prefix: str) -> str:
    if not prefix:
        return normalized_key
    return f"{prefix}/{normalized_key}"


def _require_bucket_name(resolved: _ResolvedS3Config, key: str) -> str:
    if resolved.bucket_name is None:
        raise FileStorageUnavailable("s3 storage bucket_name is required", key=key)
    return resolved.bucket_name


def _tenant_prefix(coords: AdapterTenantCoords, fallback: str) -> str:
    if "prefix" not in coords.params:
        return fallback
    return _normalize_optional_prefix(coords.params["prefix"])


def _tenant_optional_text(coords: AdapterTenantCoords, key: str, fallback: str | None) -> str | None:
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


def _tenant_bool(coords: AdapterTenantCoords, field: str, fallback: bool, key: str) -> bool:
    if field not in coords.params:
        return fallback
    normalized = coords.params[field].strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise FileStorageUnavailable(f"s3 storage tenant field {field} must be boolean", key=key)


def _metadata_from_response(key: str, response: Any) -> StoredObjectMetadata:
    return StoredObjectMetadata(
        key=key,
        content_type=_response_string(response, "ContentType"),
        size=_response_int(response, "ContentLength"),
        checksum=_response_checksum(response),
        etag=_clean_etag(_response_string(response, "ETag")),
        last_modified=_response_datetime(response, "LastModified"),
        custom=_response_metadata(response),
    )


def _response_value(response: Any, field: str) -> Any:
    if isinstance(response, Mapping):
        return response.get(field)
    return None


def _response_string(response: Any, field: str) -> str | None:
    value = _response_value(response, field)
    if isinstance(value, str):
        return value
    return None


def _response_int(response: Any, field: str) -> int | None:
    value = _response_value(response, field)
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _response_datetime(response: Any, field: str) -> datetime | None:
    value = _response_value(response, field)
    if isinstance(value, datetime):
        return value
    return None


def _response_metadata(response: Any) -> dict[str, str]:
    metadata = _response_value(response, "Metadata")
    if not isinstance(metadata, Mapping):
        return {}
    return {str(key): str(value) for key, value in metadata.items() if isinstance(key, str)}


def _response_checksum(response: Any) -> str | None:
    for field, algorithm in (
        ("ChecksumSHA256", "sha256"),
        ("ChecksumSHA1", "sha1"),
        ("ChecksumCRC64NVME", "crc64nvme"),
        ("ChecksumCRC32C", "crc32c"),
        ("ChecksumCRC32", "crc32"),
    ):
        value = _response_string(response, field)
        if value is not None:
            return f"{algorithm}:{value}"
    return None


def _clean_etag(etag: str | None) -> str | None:
    if etag is None:
        return None
    return etag.strip('"')


def _is_not_found_error(error: Exception) -> bool:
    return _provider_error_code(error) in _NOT_FOUND_CODES


def _provider_error_code(error: Exception) -> str | None:
    response = getattr(error, "response", None)
    if not isinstance(response, Mapping):
        return None
    error_payload = response.get("Error")
    if not isinstance(error_payload, Mapping):
        return None
    code = error_payload.get("Code")
    if code is None:
        return None
    return str(code)


def _raise_s3_storage_error(error: Exception, *, key: str) -> NoReturn:
    code = _provider_error_code(error)
    error_name = type(error).__name__
    if code in _NOT_FOUND_CODES:
        raise FileStorageNotFound("s3 storage object not found", key=key) from error
    if code in _PERMISSION_CODES or error_name in _PERMISSION_ERROR_NAMES:
        raise FileStoragePermissionDenied("s3 storage operation is not permitted", key=key) from error
    if code in _CONFLICT_CODES:
        raise FileStorageConflict("s3 storage operation conflicted with backend state", key=key) from error
    if code in _UNAVAILABLE_CODES or error_name in _UNAVAILABLE_ERROR_NAMES:
        raise FileStorageUnavailable("s3 storage backend is unavailable", key=key) from error
    raise FileStorageUnavailable("s3 storage operation failed", key=key) from error
