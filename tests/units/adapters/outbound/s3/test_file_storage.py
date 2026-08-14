import pytest

from arclith.adapters.context import set_tenant_context
from arclith.adapters.outbound.s3 import S3FileStorage, S3StorageConfig
from arclith.adapters.outbound.s3 import client as s3_client
from arclith.adapters.outbound.s3.config import ResolvedS3Config
from arclith.domain.models.tenant import AdapterTenantCoords, TenantContext
from arclith.domain.ports.outbound.file_storage import (
    FileStorageInvalidKey,
    FileStorageNotFound,
    FileStoragePermissionDenied,
    FileStorageUnavailable,
)
from tests.units.adapters.outbound.s3.fakes import (
    BodylessS3Client,
    FailingBody,
    FailingReadS3Client,
    FakeS3Client,
    S3ProviderError,
    chunks,
    collect,
)


@pytest.mark.asyncio
async def test_s3_file_storage_round_trips_file_and_metadata() -> None:
    client = FakeS3Client()
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
        chunks(b"", b"hello ", b"s3"),
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
    assert await collect(stream.body) == b"hello s3"
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
    client = FakeS3Client()
    storage = S3FileStorage(S3StorageConfig(bucket_name="arclith-files"), client=client)

    await storage.put("docs/readme.txt", chunks(b"content"))
    await storage.delete("docs/readme.txt")
    await storage.delete("docs/readme.txt")

    assert await storage.exists("docs/readme.txt") is False
    with pytest.raises(FileStorageNotFound):
        await storage.stat("docs/readme.txt")


@pytest.mark.asyncio
async def test_s3_file_storage_maps_provider_not_found() -> None:
    client = FakeS3Client()
    storage = S3FileStorage(S3StorageConfig(bucket_name="arclith-files"), client=client)
    client.fail("head_object", S3ProviderError("NoSuchKey"))

    with pytest.raises(FileStorageNotFound) as exc_info:
        await storage.stat("missing/object.txt")

    assert exc_info.value.key == "missing/object.txt"
    assert await storage.exists("missing/object.txt") is False


@pytest.mark.asyncio
async def test_s3_file_storage_maps_provider_permission_error() -> None:
    client = FakeS3Client()
    storage = S3FileStorage(S3StorageConfig(bucket_name="arclith-files"), client=client)
    client.fail("put_object", S3ProviderError("AccessDenied"))

    with pytest.raises(FileStoragePermissionDenied) as exc_info:
        await storage.put("docs/readme.txt", chunks(b"blocked"))

    assert exc_info.value.key == "docs/readme.txt"


@pytest.mark.asyncio
async def test_s3_file_storage_rejects_unsafe_keys() -> None:
    storage = S3FileStorage(
        S3StorageConfig(bucket_name="arclith-files"), client=FakeS3Client()
    )

    with pytest.raises(FileStorageInvalidKey):
        await storage.put("../secret.txt", chunks(b"blocked"))


@pytest.mark.asyncio
async def test_s3_file_storage_uses_tenant_context_for_target_and_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeS3Client()
    created_configs: list[ResolvedS3Config] = []

    def create_client(resolved: ResolvedS3Config) -> FakeS3Client:
        created_configs.append(resolved)
        return client

    monkeypatch.setattr(s3_client, "create_s3_client", create_client)
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
        await storage.put("docs/readme.txt", chunks(b"tenant"))
    finally:
        token.var.reset(token)

    assert client.calls[0][1]["Bucket"] == "tenant-bucket"
    assert client.calls[0][1]["Key"] == "tenant-a/docs/readme.txt"
    assert created_configs
    assert created_configs[0].region_name == "us-east-1"
    assert created_configs[0].endpoint_url == "http://minio:9000"
    assert created_configs[0].force_path_style is True
    assert created_configs[0].aws_access_key_id == "tenant-key"
    assert created_configs[0].aws_secret_access_key == "tenant-secret"
    assert created_configs[0].aws_session_token == "tenant-session"


@pytest.mark.asyncio
async def test_s3_file_storage_requires_bucket_from_config_or_tenant() -> None:
    storage = S3FileStorage(
        S3StorageConfig(bucket_name=None, multitenant=True), client=FakeS3Client()
    )

    with pytest.raises(FileStorageUnavailable, match="bucket_name") as exc_info:
        await storage.put("docs/readme.txt", chunks(b"content"))

    assert exc_info.value.key == "docs/readme.txt"


@pytest.mark.asyncio
async def test_s3_file_storage_rejects_provider_response_without_body() -> None:
    storage = S3FileStorage(
        S3StorageConfig(bucket_name="arclith-files"), client=BodylessS3Client()
    )

    with pytest.raises(FileStorageUnavailable, match="body") as exc_info:
        await storage.get("docs/readme.txt")

    assert exc_info.value.key == "docs/readme.txt"


@pytest.mark.asyncio
async def test_s3_file_storage_maps_stream_read_errors_and_closes_body() -> None:
    body = FailingBody()
    storage = S3FileStorage(
        S3StorageConfig(bucket_name="arclith-files"), client=FailingReadS3Client(body)
    )

    stream = await storage.get("docs/readme.txt")
    with pytest.raises(FileStoragePermissionDenied) as exc_info:
        await collect(stream.body)

    assert exc_info.value.key == "docs/readme.txt"
    assert body.closed is True


@pytest.mark.asyncio
async def test_s3_file_storage_lazily_reuses_default_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeS3Client()
    created_configs: list[ResolvedS3Config] = []

    def create_client(resolved: ResolvedS3Config) -> FakeS3Client:
        created_configs.append(resolved)
        return client

    monkeypatch.setattr(s3_client, "create_s3_client", create_client)
    storage = S3FileStorage(S3StorageConfig(bucket_name="arclith-files"))

    await storage.put("docs/readme.txt", chunks(b"content"))
    assert await storage.exists("docs/readme.txt") is True

    assert len(created_configs) == 1
