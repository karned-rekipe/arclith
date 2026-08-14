import pytest

from arclith.adapters.context import set_tenant_context
from arclith.adapters.outbound.azure_blob import (
    AzureBlobFileStorage,
    AzureBlobStorageConfig,
)
from arclith.adapters.outbound.azure_blob import client as azure_blob_client
from arclith.adapters.outbound.azure_blob.config import ResolvedAzureBlobConfig
from arclith.domain.models.tenant import AdapterTenantCoords, TenantContext
from arclith.domain.ports.outbound.file_storage import (
    FileStorageInvalidKey,
    FileStorageNotFound,
    FileStoragePermissionDenied,
    FileStorageUnavailable,
)
from tests.units.adapters.outbound.azure_blob.fakes import (
    AzureProviderError,
    FailingDownloader,
    FakeAzureBlobServiceClient,
    FakeContentSettings,
    FakeReadAllDownloader,
    ThreadTrackingDownloader,
    chunks,
    collect,
)


@pytest.mark.asyncio
async def test_azure_blob_file_storage_round_trips_file_and_metadata() -> None:
    client = FakeAzureBlobServiceClient()
    storage = AzureBlobFileStorage(
        AzureBlobStorageConfig(
            account_url="https://account.blob.core.windows.net",
            container_name="arclith-files",
            prefix="uploads",
        ),
        client=client,
        content_settings_factory=_fake_content_settings,
    )

    stored = await storage.put(
        "tenant-a/docs/readme.txt",
        chunks(b"", b"hello ", b"azure"),
        content_type="text/plain",
        metadata={"owner": "tenant-a"},
    )
    stream = await storage.get("tenant-a/docs/readme.txt")
    stat = await storage.stat("tenant-a/docs/readme.txt")

    assert stored.key == "tenant-a/docs/readme.txt"
    assert stored.size == 11
    assert stored.content_type == "text/plain"
    assert stored.checksum == "md5:cHJvdmlkZXItbWQ1"
    assert stored.etag == "azure-etag"
    assert stored.custom == {
        "owner": "tenant-a",
        "azure_blob_type": "BlockBlob",
        "azure_version_id": "version-a",
    }
    assert await collect(stream.body) == b"hello azure"
    assert client.last_downloader is not None
    assert client.last_downloader.adapter_closed is True
    assert stream.metadata == stat
    assert stat.size == 11
    assert stat.content_type == "text/plain"
    assert stat.checksum == "md5:cHJvdmlkZXItbWQ1"
    assert stat.etag == "azure-etag"
    assert stat.custom == stored.custom
    assert await storage.exists("tenant-a/docs/readme.txt") is True

    first_call = client.calls[0]
    assert first_call[0] == "upload_blob"
    assert first_call[1]["container_name"] == "arclith-files"
    assert first_call[1]["object_key"] == "uploads/tenant-a/docs/readme.txt"
    assert first_call[1]["content_type"] == "text/plain"
    assert first_call[1]["length"] == 11
    assert first_call[1]["overwrite"] is True
    assert first_call[1]["metadata"] == {"owner": "tenant-a"}


@pytest.mark.asyncio
async def test_azure_blob_file_storage_delete_is_idempotent() -> None:
    client = FakeAzureBlobServiceClient()
    storage = AzureBlobFileStorage(
        DEFAULT_AZURE_CONFIG,
        client=client,
        content_settings_factory=_fake_content_settings,
    )

    await storage.put("docs/readme.txt", chunks(b"content"))
    await storage.delete("docs/readme.txt")
    await storage.delete("docs/readme.txt")

    assert await storage.exists("docs/readme.txt") is False
    with pytest.raises(FileStorageNotFound):
        await storage.stat("docs/readme.txt")


@pytest.mark.asyncio
async def test_azure_blob_file_storage_maps_provider_not_found() -> None:
    storage = AzureBlobFileStorage(
        DEFAULT_AZURE_CONFIG,
        client=FakeAzureBlobServiceClient(),
        content_settings_factory=_fake_content_settings,
    )

    with pytest.raises(FileStorageNotFound) as exc_info:
        await storage.stat("missing/object.txt")

    assert exc_info.value.key == "missing/object.txt"
    assert await storage.exists("missing/object.txt") is False


@pytest.mark.asyncio
async def test_azure_blob_file_storage_maps_provider_permission_error() -> None:
    client = FakeAzureBlobServiceClient()
    storage = AzureBlobFileStorage(
        DEFAULT_AZURE_CONFIG,
        client=client,
        content_settings_factory=_fake_content_settings,
    )
    client.fail(
        "upload_blob",
        AzureProviderError("AuthorizationPermissionMismatch", status_code=403),
    )

    with pytest.raises(FileStoragePermissionDenied) as exc_info:
        await storage.put("docs/readme.txt", chunks(b"blocked"))

    assert exc_info.value.key == "docs/readme.txt"


@pytest.mark.asyncio
async def test_azure_blob_file_storage_rejects_unsafe_keys() -> None:
    storage = AzureBlobFileStorage(
        DEFAULT_AZURE_CONFIG,
        client=FakeAzureBlobServiceClient(),
        content_settings_factory=_fake_content_settings,
    )

    with pytest.raises(FileStorageInvalidKey):
        await storage.put("../secret.txt", chunks(b"blocked"))


@pytest.mark.asyncio
async def test_azure_blob_file_storage_uses_tenant_context_for_target_and_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeAzureBlobServiceClient()
    created_configs: list[ResolvedAzureBlobConfig] = []

    def create_client(resolved: ResolvedAzureBlobConfig) -> FakeAzureBlobServiceClient:
        created_configs.append(resolved)
        return client

    monkeypatch.setattr(
        azure_blob_client,
        "create_azure_blob_service_client",
        create_client,
    )
    token = set_tenant_context(
        TenantContext(
            adapters={
                "azure-blob": AdapterTenantCoords(
                    params={
                        "blob_service_url": "https://tenant.blob.core.windows.net",
                        "container": "tenant-container",
                        "prefix": "tenant-a",
                        "connection_string": "UseDevelopmentStorage=true",
                    }
                )
            }
        )
    )
    try:
        storage = AzureBlobFileStorage(
            AzureBlobStorageConfig(
                account_url="https://fallback.blob.core.windows.net",
                container_name=None,
                prefix="fallback",
                multitenant=True,
            )
        )
        await storage.put("docs/readme.txt", chunks(b"tenant"))
    finally:
        token.var.reset(token)

    assert client.calls[0][1]["container_name"] == "tenant-container"
    assert client.calls[0][1]["object_key"] == "tenant-a/docs/readme.txt"
    assert created_configs
    assert created_configs[0].account_url == "https://tenant.blob.core.windows.net"
    assert created_configs[0].connection_string == "UseDevelopmentStorage=true"


@pytest.mark.asyncio
async def test_azure_blob_file_storage_requires_container_from_config_or_tenant() -> None:
    storage = AzureBlobFileStorage(
        AzureBlobStorageConfig(container_name=None, multitenant=True),
        client=FakeAzureBlobServiceClient(),
        content_settings_factory=_fake_content_settings,
    )

    with pytest.raises(FileStorageUnavailable, match="container_name") as exc_info:
        await storage.put("docs/readme.txt", chunks(b"content"))

    assert exc_info.value.key == "docs/readme.txt"


@pytest.mark.asyncio
async def test_azure_blob_file_storage_rejects_provider_response_without_body() -> None:
    client = FakeAzureBlobServiceClient()
    storage = AzureBlobFileStorage(
        DEFAULT_AZURE_CONFIG,
        client=client,
        content_settings_factory=_fake_content_settings,
    )
    await storage.put("docs/readme.txt", chunks(b"content"))
    client.downloaders[("arclith-files", "docs/readme.txt")] = object()

    with pytest.raises(FileStorageUnavailable, match="body") as exc_info:
        await storage.get("docs/readme.txt")

    assert exc_info.value.key == "docs/readme.txt"


@pytest.mark.asyncio
async def test_azure_blob_file_storage_reads_downloader_readall_fallback() -> None:
    client = FakeAzureBlobServiceClient()
    body = FakeReadAllDownloader(b"content")
    storage = AzureBlobFileStorage(
        DEFAULT_AZURE_CONFIG,
        client=client,
        content_settings_factory=_fake_content_settings,
    )
    await storage.put("docs/readme.txt", chunks(b"content"))
    client.downloaders[("arclith-files", "docs/readme.txt")] = body

    stream = await storage.get("docs/readme.txt")

    assert await collect(stream.body) == b"content"
    assert body.closed is True


@pytest.mark.asyncio
async def test_azure_blob_file_storage_consumes_chunks_on_single_thread() -> None:
    client = FakeAzureBlobServiceClient()
    body = ThreadTrackingDownloader(b"hello ", b"azure")
    storage = AzureBlobFileStorage(
        DEFAULT_AZURE_CONFIG,
        client=client,
        content_settings_factory=_fake_content_settings,
    )
    await storage.put("docs/readme.txt", chunks(b"hello azure"))
    client.downloaders[("arclith-files", "docs/readme.txt")] = body

    stream = await storage.get("docs/readme.txt")

    assert await collect(stream.body) == b"hello azure"
    assert len(body.thread_ids) == 1
    assert body.closed is True


@pytest.mark.asyncio
async def test_azure_blob_file_storage_maps_stream_read_errors_and_closes_body() -> None:
    client = FakeAzureBlobServiceClient()
    body = FailingDownloader()
    storage = AzureBlobFileStorage(
        DEFAULT_AZURE_CONFIG,
        client=client,
        content_settings_factory=_fake_content_settings,
    )
    await storage.put("docs/readme.txt", chunks(b"content"))
    client.downloaders[("arclith-files", "docs/readme.txt")] = body

    stream = await storage.get("docs/readme.txt")
    with pytest.raises(FileStoragePermissionDenied) as exc_info:
        await collect(stream.body)

    assert exc_info.value.key == "docs/readme.txt"
    assert body.closed is True


@pytest.mark.asyncio
async def test_azure_blob_file_storage_lazily_reuses_default_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeAzureBlobServiceClient()
    created_configs: list[ResolvedAzureBlobConfig] = []

    def create_client(resolved: ResolvedAzureBlobConfig) -> FakeAzureBlobServiceClient:
        created_configs.append(resolved)
        return client

    monkeypatch.setattr(
        azure_blob_client,
        "create_azure_blob_service_client",
        create_client,
    )
    storage = AzureBlobFileStorage(
        AzureBlobStorageConfig(
            account_url="https://account.blob.core.windows.net",
            container_name="arclith-files",
        )
    )

    await storage.put("docs/readme.txt", chunks(b"content"))
    assert await storage.exists("docs/readme.txt") is True

    assert len(created_configs) == 1


def _fake_content_settings(content_type: str) -> FakeContentSettings:
    return FakeContentSettings(content_type=content_type)


DEFAULT_AZURE_CONFIG = AzureBlobStorageConfig(
    account_url="https://account.blob.core.windows.net",
    container_name="arclith-files",
)
