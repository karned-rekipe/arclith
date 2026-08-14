import pytest

from arclith.adapters.context import set_tenant_context
from arclith.adapters.outbound.gcs import GCSFileStorage, GCSStorageConfig
from arclith.adapters.outbound.gcs import client as gcs_client
from arclith.adapters.outbound.gcs.config import ResolvedGCSConfig
from arclith.domain.models.tenant import AdapterTenantCoords, TenantContext
from arclith.domain.ports.outbound.file_storage import (
    FileStorageInvalidKey,
    FileStorageNotFound,
    FileStoragePermissionDenied,
    FileStorageUnavailable,
)
from tests.units.adapters.outbound.gcs.fakes import (
    FailingBody,
    FakeGCSClient,
    GCSProviderError,
    chunks,
    collect,
)


@pytest.mark.asyncio
async def test_gcs_file_storage_round_trips_file_and_metadata() -> None:
    client = FakeGCSClient()
    storage = GCSFileStorage(
        GCSStorageConfig(
            bucket_name="arclith-files",
            prefix="uploads",
            project_id="project-a",
        ),
        client=client,
    )

    stored = await storage.put(
        "tenant-a/docs/readme.txt",
        chunks(b"", b"hello ", b"gcs"),
        content_type="text/plain",
        metadata={"owner": "tenant-a"},
    )
    stream = await storage.get("tenant-a/docs/readme.txt")
    stat = await storage.stat("tenant-a/docs/readme.txt")

    assert stored.key == "tenant-a/docs/readme.txt"
    assert stored.size == 9
    assert stored.content_type == "text/plain"
    assert stored.checksum == "crc32c:provider-crc32c"
    assert stored.etag == "gcs-etag"
    assert stored.custom == {
        "owner": "tenant-a",
        "gcs_generation": "1700000000000000",
        "gcs_metageneration": "1",
    }
    assert await collect(stream.body) == b"hello gcs"
    assert client.last_body is not None
    assert client.last_body.adapter_closed is True
    assert stream.metadata == stat
    assert stat.size == 9
    assert stat.content_type == "text/plain"
    assert stat.checksum == "crc32c:provider-crc32c"
    assert stat.etag == "gcs-etag"
    assert stat.custom == stored.custom
    assert await storage.exists("tenant-a/docs/readme.txt") is True

    first_call = client.calls[0]
    assert first_call[0] == "upload_from_file"
    assert first_call[1]["bucket_name"] == "arclith-files"
    assert first_call[1]["object_key"] == "uploads/tenant-a/docs/readme.txt"
    assert first_call[1]["content_type"] == "text/plain"
    assert first_call[1]["size"] == 9
    assert first_call[1]["rewind"] is False
    assert first_call[1]["metadata"] == {"owner": "tenant-a"}


@pytest.mark.asyncio
async def test_gcs_file_storage_delete_is_idempotent() -> None:
    client = FakeGCSClient()
    storage = GCSFileStorage(DEFAULT_GCS_CONFIG, client=client)

    await storage.put("docs/readme.txt", chunks(b"content"))
    await storage.delete("docs/readme.txt")
    await storage.delete("docs/readme.txt")

    assert await storage.exists("docs/readme.txt") is False
    with pytest.raises(FileStorageNotFound):
        await storage.stat("docs/readme.txt")


@pytest.mark.asyncio
async def test_gcs_file_storage_maps_provider_not_found() -> None:
    storage = GCSFileStorage(DEFAULT_GCS_CONFIG, client=FakeGCSClient())

    with pytest.raises(FileStorageNotFound) as exc_info:
        await storage.stat("missing/object.txt")

    assert exc_info.value.key == "missing/object.txt"
    assert await storage.exists("missing/object.txt") is False


@pytest.mark.asyncio
async def test_gcs_file_storage_maps_provider_permission_error() -> None:
    client = FakeGCSClient()
    storage = GCSFileStorage(DEFAULT_GCS_CONFIG, client=client)
    client.fail("upload_from_file", GCSProviderError(403))

    with pytest.raises(FileStoragePermissionDenied) as exc_info:
        await storage.put("docs/readme.txt", chunks(b"blocked"))

    assert exc_info.value.key == "docs/readme.txt"


@pytest.mark.asyncio
async def test_gcs_file_storage_rejects_unsafe_keys() -> None:
    storage = GCSFileStorage(DEFAULT_GCS_CONFIG, client=FakeGCSClient())

    with pytest.raises(FileStorageInvalidKey):
        await storage.put("../secret.txt", chunks(b"blocked"))


@pytest.mark.asyncio
async def test_gcs_file_storage_uses_tenant_context_for_target_and_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeGCSClient()
    created_configs: list[ResolvedGCSConfig] = []

    def create_client(resolved: ResolvedGCSConfig) -> FakeGCSClient:
        created_configs.append(resolved)
        return client

    monkeypatch.setattr(gcs_client, "create_gcs_client", create_client)
    token = set_tenant_context(
        TenantContext(
            adapters={
                "gcs": AdapterTenantCoords(
                    params={
                        "bucket_name": "tenant-bucket",
                        "prefix": "tenant-a",
                        "project_id": "tenant-project",
                        "credentials_path": "/run/secrets/gcs.json",
                        "credentials_json_b64": "eyJ0eXBlIjoic2VydmljZV9hY2NvdW50In0=",
                    }
                )
            }
        )
    )
    try:
        storage = GCSFileStorage(
            GCSStorageConfig(
                bucket_name=None,
                prefix="fallback",
                project_id="fallback-project",
                multitenant=True,
            )
        )
        await storage.put("docs/readme.txt", chunks(b"tenant"))
    finally:
        token.var.reset(token)

    assert client.calls[0][1]["bucket_name"] == "tenant-bucket"
    assert client.calls[0][1]["object_key"] == "tenant-a/docs/readme.txt"
    assert created_configs
    assert created_configs[0].project_id == "tenant-project"
    assert created_configs[0].credentials_path == "/run/secrets/gcs.json"
    assert (
        created_configs[0].credentials_json_b64
        == "eyJ0eXBlIjoic2VydmljZV9hY2NvdW50In0="
    )


@pytest.mark.asyncio
async def test_gcs_file_storage_requires_bucket_from_config_or_tenant() -> None:
    storage = GCSFileStorage(
        GCSStorageConfig(bucket_name=None, multitenant=True), client=FakeGCSClient()
    )

    with pytest.raises(FileStorageUnavailable, match="bucket_name") as exc_info:
        await storage.put("docs/readme.txt", chunks(b"content"))

    assert exc_info.value.key == "docs/readme.txt"


@pytest.mark.asyncio
async def test_gcs_file_storage_rejects_provider_response_without_body() -> None:
    client = FakeGCSClient()
    storage = GCSFileStorage(DEFAULT_GCS_CONFIG, client=client)
    await storage.put("docs/readme.txt", chunks(b"content"))
    client.open_bodies[("arclith-files", "docs/readme.txt")] = object()

    with pytest.raises(FileStorageUnavailable, match="body") as exc_info:
        await storage.get("docs/readme.txt")

    assert exc_info.value.key == "docs/readme.txt"


@pytest.mark.asyncio
async def test_gcs_file_storage_maps_stream_read_errors_and_closes_body() -> None:
    client = FakeGCSClient()
    body = FailingBody()
    storage = GCSFileStorage(DEFAULT_GCS_CONFIG, client=client)
    await storage.put("docs/readme.txt", chunks(b"content"))
    client.open_bodies[("arclith-files", "docs/readme.txt")] = body

    stream = await storage.get("docs/readme.txt")
    with pytest.raises(FileStoragePermissionDenied) as exc_info:
        await collect(stream.body)

    assert exc_info.value.key == "docs/readme.txt"
    assert body.closed is True


@pytest.mark.asyncio
async def test_gcs_file_storage_lazily_reuses_default_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeGCSClient()
    created_configs: list[ResolvedGCSConfig] = []

    def create_client(resolved: ResolvedGCSConfig) -> FakeGCSClient:
        created_configs.append(resolved)
        return client

    monkeypatch.setattr(gcs_client, "create_gcs_client", create_client)
    storage = GCSFileStorage(GCSStorageConfig(bucket_name="arclith-files"))

    await storage.put("docs/readme.txt", chunks(b"content"))
    assert await storage.exists("docs/readme.txt") is True

    assert len(created_configs) == 1


DEFAULT_GCS_CONFIG = GCSStorageConfig(bucket_name="arclith-files")
