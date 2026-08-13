from collections.abc import AsyncIterator
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import pytest

from arclith.adapters.context import set_tenant_context
from arclith.adapters.outbound.s3 import S3FileStorage, S3StorageConfig
from arclith.adapters.outbound.s3 import file_storage as s3_file_storage
from arclith.domain.models.tenant import AdapterTenantCoords, TenantContext
from arclith.domain.ports.outbound.file_storage import (
    FileStorageConflict,
    FileStorageInvalidKey,
    FileStorageNotFound,
    FileStoragePermissionDenied,
    FileStorageUnavailable,
)


class _S3ProviderError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _CloseTrackingBody(BytesIO):
    adapter_closed: bool = False

    def close(self) -> None:
        self.adapter_closed = True
        super().close()


class _FailingBody:
    closed: bool = False

    def read(self, _size: int) -> bytes:
        raise _S3ProviderError("AccessDenied")

    def close(self) -> None:
        self.closed = True


class _FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        self.errors: dict[str, Exception] = {}
        self.last_body: _CloseTrackingBody | None = None

    def fail(self, operation: str, error: Exception) -> None:
        self.errors[operation] = error

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        self._raise_if_needed("put_object")
        body = kwargs["Body"].read()
        record = {
            "Body": body,
            "ContentType": kwargs.get("ContentType"),
            "ContentLength": len(body),
            "ETag": '"etag-123"',
            "ChecksumSHA256": "provider-sha256",
            "LastModified": datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
            "Metadata": kwargs.get("Metadata", {}),
        }
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = record
        self.calls.append(("put_object", dict(kwargs)))
        return {"ETag": record["ETag"]}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self._raise_if_needed("get_object")
        self.calls.append(("get_object", dict(kwargs)))
        record = self._record_for(kwargs["Bucket"], kwargs["Key"])
        response = dict(record)
        self.last_body = _CloseTrackingBody(record["Body"])
        response["Body"] = self.last_body
        return response

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self._raise_if_needed("head_object")
        self.calls.append(("head_object", dict(kwargs)))
        record = self._record_for(kwargs["Bucket"], kwargs["Key"])
        return {key: value for key, value in record.items() if key != "Body"}

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self._raise_if_needed("delete_object")
        self.calls.append(("delete_object", dict(kwargs)))
        self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)
        return {}

    def _record_for(self, bucket_name: str, object_key: str) -> dict[str, Any]:
        key = (bucket_name, object_key)
        if key not in self.objects:
            raise _S3ProviderError("NoSuchKey")
        return self.objects[key]

    def _raise_if_needed(self, operation: str) -> None:
        error = self.errors.get(operation)
        if error is not None:
            raise error


class _BodylessS3Client(_FakeS3Client):
    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_object", dict(kwargs)))
        return {}


class _FailingReadS3Client(_FakeS3Client):
    def __init__(self, body: _FailingBody) -> None:
        super().__init__()
        self._body = body

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_object", dict(kwargs)))
        return {"Body": self._body}


async def _chunks(*items: bytes) -> AsyncIterator[bytes]:
    for item in items:
        yield item


async def _collect(stream: AsyncIterator[bytes]) -> bytes:
    body = bytearray()
    async for chunk in stream:
        body.extend(chunk)
    return bytes(body)


@pytest.mark.asyncio
async def test_s3_file_storage_round_trips_file_and_metadata() -> None:
    client = _FakeS3Client()
    storage = S3FileStorage(
        S3StorageConfig(
            bucket_name="arclith-files",
            prefix="uploads",
            region_name="eu-west-3",
            endpoint_url="http://127.0.0.1:9000",
            force_path_style=True,
        ),
        client=client,
    )

    stored = await storage.put(
        "tenant-a/docs/readme.txt",
        _chunks(b"", b"hello ", b"s3"),
        content_type="text/plain",
        metadata={"owner": "tenant-a"},
    )
    stream = await storage.get("tenant-a/docs/readme.txt")
    stat = await storage.stat("tenant-a/docs/readme.txt")

    assert stored.key == "tenant-a/docs/readme.txt"
    assert stored.size == 8
    assert stored.content_type == "text/plain"
    assert stored.checksum is not None
    assert stored.etag == "etag-123"
    assert stored.custom == {"owner": "tenant-a"}
    assert await _collect(stream.body) == b"hello s3"
    assert client.last_body is not None
    assert client.last_body.adapter_closed is True
    assert stream.metadata == stat
    assert stat.size == 8
    assert stat.content_type == "text/plain"
    assert stat.checksum == "sha256:provider-sha256"
    assert stat.etag == "etag-123"
    assert stat.custom == {"owner": "tenant-a"}
    assert await storage.exists("tenant-a/docs/readme.txt") is True

    first_call = client.calls[0]
    assert first_call[0] == "put_object"
    assert first_call[1]["Bucket"] == "arclith-files"
    assert first_call[1]["Key"] == "uploads/tenant-a/docs/readme.txt"
    assert first_call[1]["ContentType"] == "text/plain"
    assert first_call[1]["Metadata"] == {"owner": "tenant-a"}


@pytest.mark.asyncio
async def test_s3_file_storage_delete_is_idempotent() -> None:
    client = _FakeS3Client()
    storage = S3FileStorage(S3StorageConfig(bucket_name="arclith-files"), client=client)

    await storage.put("docs/readme.txt", _chunks(b"content"))
    await storage.delete("docs/readme.txt")
    await storage.delete("docs/readme.txt")

    assert await storage.exists("docs/readme.txt") is False
    with pytest.raises(FileStorageNotFound):
        await storage.stat("docs/readme.txt")


@pytest.mark.asyncio
async def test_s3_file_storage_maps_provider_not_found() -> None:
    client = _FakeS3Client()
    storage = S3FileStorage(S3StorageConfig(bucket_name="arclith-files"), client=client)
    client.fail("head_object", _S3ProviderError("NoSuchKey"))

    with pytest.raises(FileStorageNotFound) as exc_info:
        await storage.stat("missing/object.txt")

    assert exc_info.value.key == "missing/object.txt"
    assert await storage.exists("missing/object.txt") is False


@pytest.mark.asyncio
async def test_s3_file_storage_maps_provider_permission_error() -> None:
    client = _FakeS3Client()
    storage = S3FileStorage(S3StorageConfig(bucket_name="arclith-files"), client=client)
    client.fail("put_object", _S3ProviderError("AccessDenied"))

    with pytest.raises(FileStoragePermissionDenied) as exc_info:
        await storage.put("docs/readme.txt", _chunks(b"blocked"))

    assert exc_info.value.key == "docs/readme.txt"


@pytest.mark.asyncio
async def test_s3_file_storage_rejects_unsafe_keys() -> None:
    storage = S3FileStorage(S3StorageConfig(bucket_name="arclith-files"), client=_FakeS3Client())

    with pytest.raises(FileStorageInvalidKey):
        await storage.put("../secret.txt", _chunks(b"blocked"))


@pytest.mark.asyncio
async def test_s3_file_storage_uses_tenant_context_for_target_and_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeS3Client()
    created_configs: list[object] = []

    def create_client(resolved: object) -> _FakeS3Client:
        created_configs.append(resolved)
        return client

    monkeypatch.setattr(s3_file_storage, "_create_s3_client", create_client)
    token = set_tenant_context(
        TenantContext(
            adapters={
                "s3": AdapterTenantCoords(
                    params={
                        "bucket_name": "tenant-bucket",
                        "prefix": "tenant-a",
                        "region_name": "us-east-1",
                        "endpoint_url": "http://minio:9000",
                        "force_path_style": "true",
                        "aws_access_key_id": "tenant-key",
                        "aws_secret_access_key": "tenant-secret",
                        "aws_session_token": "tenant-session",
                    }
                )
            }
        )
    )
    try:
        storage = S3FileStorage(
            S3StorageConfig(
                bucket_name=None,
                prefix="fallback",
                region_name="eu-west-3",
                multitenant=True,
            )
        )
        await storage.put("docs/readme.txt", _chunks(b"tenant"))
    finally:
        token.var.reset(token)

    assert client.calls[0][1]["Bucket"] == "tenant-bucket"
    assert client.calls[0][1]["Key"] == "tenant-a/docs/readme.txt"
    assert created_configs
    created_config = created_configs[0]
    assert getattr(created_config, "region_name") == "us-east-1"
    assert getattr(created_config, "endpoint_url") == "http://minio:9000"
    assert getattr(created_config, "force_path_style") is True
    assert getattr(created_config, "aws_access_key_id") == "tenant-key"
    assert getattr(created_config, "aws_secret_access_key") == "tenant-secret"
    assert getattr(created_config, "aws_session_token") == "tenant-session"


@pytest.mark.asyncio
async def test_s3_file_storage_uses_tenant_defaults_when_fields_are_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeS3Client()

    monkeypatch.setattr(s3_file_storage, "_create_s3_client", lambda resolved: client)
    token = set_tenant_context(
        TenantContext(adapters={"s3": AdapterTenantCoords(params={"bucket_name": "tenant-bucket"})})
    )
    try:
        storage = S3FileStorage(
            S3StorageConfig(
                bucket_name="fallback-bucket",
                prefix="fallback-prefix",
                region_name=" ",
                multitenant=True,
            )
        )
        await storage.put("docs/readme.txt", _chunks(b"tenant"))
    finally:
        token.var.reset(token)

    assert client.calls[0][1]["Bucket"] == "tenant-bucket"
    assert client.calls[0][1]["Key"] == "fallback-prefix/docs/readme.txt"


@pytest.mark.asyncio
async def test_s3_file_storage_rejects_invalid_tenant_boolean() -> None:
    storage = S3FileStorage(S3StorageConfig(bucket_name="fallback", multitenant=True), client=_FakeS3Client())
    token = set_tenant_context(
        TenantContext(
            adapters={
                "s3": AdapterTenantCoords(
                    params={
                        "bucket_name": "tenant-bucket",
                        "force_path_style": "maybe",
                    }
                )
            }
        )
    )
    try:
        with pytest.raises(FileStorageUnavailable, match="force_path_style") as exc_info:
            await storage.put("docs/readme.txt", _chunks(b"content"))
    finally:
        token.var.reset(token)

    assert exc_info.value.key == "docs/readme.txt"


@pytest.mark.asyncio
async def test_s3_file_storage_requires_bucket_from_config_or_tenant() -> None:
    storage = S3FileStorage(S3StorageConfig(bucket_name=None, multitenant=True), client=_FakeS3Client())

    with pytest.raises(FileStorageUnavailable, match="bucket_name") as exc_info:
        await storage.put("docs/readme.txt", _chunks(b"content"))

    assert exc_info.value.key == "docs/readme.txt"


@pytest.mark.asyncio
async def test_s3_file_storage_rejects_provider_response_without_body() -> None:
    storage = S3FileStorage(S3StorageConfig(bucket_name="arclith-files"), client=_BodylessS3Client())

    with pytest.raises(FileStorageUnavailable, match="body") as exc_info:
        await storage.get("docs/readme.txt")

    assert exc_info.value.key == "docs/readme.txt"


@pytest.mark.asyncio
async def test_s3_file_storage_maps_stream_read_errors_and_closes_body() -> None:
    body = _FailingBody()
    storage = S3FileStorage(S3StorageConfig(bucket_name="arclith-files"), client=_FailingReadS3Client(body))

    stream = await storage.get("docs/readme.txt")
    with pytest.raises(FileStoragePermissionDenied) as exc_info:
        await _collect(stream.body)

    assert exc_info.value.key == "docs/readme.txt"
    assert body.closed is True


@pytest.mark.asyncio
async def test_s3_file_storage_lazily_reuses_default_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeS3Client()
    created_configs: list[object] = []

    def create_client(resolved: object) -> _FakeS3Client:
        created_configs.append(resolved)
        return client

    monkeypatch.setattr(s3_file_storage, "_create_s3_client", create_client)
    storage = S3FileStorage(S3StorageConfig(bucket_name="arclith-files"))

    await storage.put("docs/readme.txt", _chunks(b"content"))
    assert await storage.exists("docs/readme.txt") is True

    assert len(created_configs) == 1


@pytest.mark.parametrize(
    ("error", "expected_error"),
    [
        (_S3ProviderError("PreconditionFailed"), FileStorageConflict),
        (_S3ProviderError("NoSuchBucket"), FileStorageUnavailable),
        (_S3ProviderError("UnexpectedProviderCode"), FileStorageUnavailable),
    ],
)
@pytest.mark.asyncio
async def test_s3_file_storage_maps_provider_errors(
    error: Exception,
    expected_error: type[Exception],
) -> None:
    client = _FakeS3Client()
    storage = S3FileStorage(S3StorageConfig(bucket_name="arclith-files"), client=client)
    client.fail("head_object", error)

    with pytest.raises(expected_error):
        await storage.stat("docs/readme.txt")


def test_s3_response_helpers_tolerate_incomplete_provider_payloads() -> None:
    empty_metadata = s3_file_storage._metadata_from_response("docs/readme.txt", object())
    invalid_metadata = s3_file_storage._metadata_from_response(
        "docs/readme.txt",
        {
            "ContentType": 42,
            "ContentLength": -1,
            "ETag": None,
            "LastModified": "not-a-date",
            "Metadata": "not-a-mapping",
        },
    )

    assert empty_metadata.content_type is None
    assert empty_metadata.size is None
    assert empty_metadata.etag is None
    assert empty_metadata.custom == {}
    assert invalid_metadata.content_type is None
    assert invalid_metadata.size is None
    assert invalid_metadata.last_modified is None
    assert invalid_metadata.custom == {}
    assert s3_file_storage._response_checksum({"ChecksumCRC32": "crc32-value"}) == "crc32:crc32-value"
    assert s3_file_storage._response_checksum({}) is None
    assert s3_file_storage._clean_etag(None) is None


def test_s3_error_code_parsing_tolerates_incomplete_payloads() -> None:
    class ResponseIsNotMappingError(Exception):
        response = "not-a-mapping"

    class ErrorPayloadIsNotMappingError(Exception):
        response = {"Error": "not-a-mapping"}

    class CodeIsMissingError(Exception):
        response = {"Error": {}}

    assert s3_file_storage._provider_error_code(ResponseIsNotMappingError()) is None
    assert s3_file_storage._provider_error_code(ErrorPayloadIsNotMappingError()) is None
    assert s3_file_storage._provider_error_code(CodeIsMissingError()) is None


def test_safe_create_s3_client_preserves_storage_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = FileStorageUnavailable("explicit setup error")

    def create_client(_resolved: object) -> object:
        raise expected

    monkeypatch.setattr(s3_file_storage, "_create_s3_client", create_client)

    with pytest.raises(FileStorageUnavailable) as exc_info:
        s3_file_storage._safe_create_s3_client(
            s3_file_storage._ResolvedS3Config(
                bucket_name="arclith-files",
                prefix="",
                region_name=None,
                endpoint_url=None,
                force_path_style=False,
            ),
            "docs/readme.txt",
        )

    assert exc_info.value is expected


def test_safe_create_s3_client_maps_setup_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def create_client(_resolved: object) -> object:
        raise _S3ProviderError("AccessDenied")

    monkeypatch.setattr(s3_file_storage, "_create_s3_client", create_client)

    with pytest.raises(FileStoragePermissionDenied) as exc_info:
        s3_file_storage._safe_create_s3_client(
            s3_file_storage._ResolvedS3Config(
                bucket_name="arclith-files",
                prefix="",
                region_name=None,
                endpoint_url=None,
                force_path_style=False,
            ),
            "docs/readme.txt",
        )

    assert exc_info.value.key == "docs/readme.txt"


def test_create_s3_client_uses_sdk_session_and_path_style(monkeypatch: pytest.MonkeyPatch) -> None:
    import boto3

    captured: dict[str, Any] = {}
    expected_client = object()

    class FakeSession:
        def __init__(self, **kwargs: Any) -> None:
            captured["session"] = kwargs

        def client(self, service_name: str, **kwargs: Any) -> object:
            captured["service_name"] = service_name
            captured["client"] = kwargs
            return expected_client

    monkeypatch.setattr(boto3, "Session", FakeSession)

    client = s3_file_storage._create_s3_client(
        s3_file_storage._ResolvedS3Config(
            bucket_name="arclith-files",
            prefix="uploads",
            region_name="eu-west-3",
            endpoint_url="http://minio:9000",
            force_path_style=True,
            profile_name="tenant-profile",
            aws_access_key_id="tenant-key",
            aws_secret_access_key="tenant-secret",
            aws_session_token="tenant-session",
        )
    )

    assert client is expected_client
    assert captured["session"] == {
        "profile_name": "tenant-profile",
        "region_name": "eu-west-3",
        "aws_access_key_id": "tenant-key",
        "aws_secret_access_key": "tenant-secret",
        "aws_session_token": "tenant-session",
    }
    assert captured["service_name"] == "s3"
    assert captured["client"]["endpoint_url"] == "http://minio:9000"
    assert captured["client"]["config"].s3 == {"addressing_style": "path"}

    captured.clear()
    s3_file_storage._create_s3_client(
        s3_file_storage._ResolvedS3Config(
            bucket_name="arclith-files",
            prefix="",
            region_name=None,
            endpoint_url=None,
            force_path_style=False,
        )
    )

    assert captured["session"] == {}
    assert captured["service_name"] == "s3"
    assert captured["client"] == {}
