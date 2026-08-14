from collections.abc import AsyncIterator
from datetime import UTC, datetime
import threading
from typing import Any


class AzureProviderError(Exception):
    def __init__(
        self,
        error_code: str | None = None,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(error_code or str(status_code))
        self.error_code = error_code
        self.status_code = status_code


class FakeContentSettings:
    def __init__(
        self,
        *,
        content_type: str | None = None,
        content_md5: bytes | None = b"provider-md5",
    ) -> None:
        self.content_type = content_type
        self.content_md5 = content_md5


class FakeAzureDownloader:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.adapter_closed = False

    def chunks(self) -> Any:
        midpoint = max(1, len(self._body) // 2)
        yield self._body[:midpoint]
        yield self._body[midpoint:]

    def close(self) -> None:
        self.adapter_closed = True


class FakeReadAllDownloader:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.closed = False

    def readall(self) -> bytes:
        return self._body

    def close(self) -> None:
        self.closed = True


class ThreadTrackingDownloader:
    def __init__(self, *chunks: bytes) -> None:
        self._chunks = chunks
        self.closed = False
        self.thread_ids: set[int] = set()

    def chunks(self) -> Any:
        for chunk in self._chunks:
            self.thread_ids.add(threading.get_ident())
            yield chunk

    def close(self) -> None:
        self.closed = True


class FailingDownloader:
    def __init__(self) -> None:
        self.closed = False

    def chunks(self) -> Any:
        raise AzureProviderError("AuthorizationPermissionMismatch", status_code=403)
        yield b""  # pragma: no cover

    def close(self) -> None:
        self.closed = True


class FakeAzureBlobServiceClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        self.errors: dict[str, Exception] = {}
        self.downloaders: dict[tuple[str, str], Any] = {}
        self.last_downloader: FakeAzureDownloader | None = None

    def get_blob_client(self, *, container: str, blob: str) -> "FakeAzureBlobClient":
        return FakeAzureBlobClient(self, container, blob)

    def fail(self, operation: str, error: Exception) -> None:
        self.errors[operation] = error

    def _raise_if_needed(self, operation: str) -> None:
        error = self.errors.get(operation)
        if error is not None:
            raise error


class FakeAzureBlobClient:
    def __init__(
        self,
        client: FakeAzureBlobServiceClient,
        container_name: str,
        object_key: str,
    ) -> None:
        self._client = client
        self.container_name = container_name
        self.object_key = object_key

    def upload_blob(
        self,
        data: Any,
        *,
        overwrite: bool = False,
        length: int | None = None,
        metadata: dict[str, str] | None = None,
        content_settings: FakeContentSettings | None = None,
        **kwargs: Any,
    ) -> None:
        self._client._raise_if_needed("upload_blob")
        body = data.read()
        record = {
            "Body": body,
            "content_type": (
                content_settings.content_type if content_settings is not None else None
            ),
            "content_md5": (
                content_settings.content_md5 if content_settings is not None else None
            ),
            "size": len(body),
            "etag": '"azure-etag"',
            "last_modified": datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
            "metadata": dict(metadata or {}),
            "blob_type": "BlockBlob",
            "version_id": "version-a",
        }
        self._client.objects[self._record_key] = record
        self._client.calls.append(
            (
                "upload_blob",
                {
                    "container_name": self.container_name,
                    "object_key": self.object_key,
                    "overwrite": overwrite,
                    "length": length,
                    "metadata": dict(metadata or {}),
                    "content_type": record["content_type"],
                    **kwargs,
                },
            )
        )

    def get_blob_properties(self, **kwargs: Any) -> dict[str, Any]:
        self._client._raise_if_needed("get_blob_properties")
        self._client.calls.append(
            (
                "get_blob_properties",
                {
                    "container_name": self.container_name,
                    "object_key": self.object_key,
                    **kwargs,
                },
            )
        )
        return self._record_for()

    def download_blob(self, **kwargs: Any) -> Any:
        self._client._raise_if_needed("download_blob")
        self._client.calls.append(
            (
                "download_blob",
                {
                    "container_name": self.container_name,
                    "object_key": self.object_key,
                    **kwargs,
                },
            )
        )
        record = self._record_for()
        override = self._client.downloaders.get(self._record_key)
        if override is not None:
            return override
        self._client.last_downloader = FakeAzureDownloader(record["Body"])
        return self._client.last_downloader

    def delete_blob(self, **kwargs: Any) -> None:
        self._client._raise_if_needed("delete_blob")
        self._client.calls.append(
            (
                "delete_blob",
                {
                    "container_name": self.container_name,
                    "object_key": self.object_key,
                    **kwargs,
                },
            )
        )
        self._record_for()
        self._client.objects.pop(self._record_key, None)

    def exists(self, **kwargs: Any) -> bool:
        self._client._raise_if_needed("exists")
        self._client.calls.append(
            (
                "exists",
                {
                    "container_name": self.container_name,
                    "object_key": self.object_key,
                    **kwargs,
                },
            )
        )
        return self._record_key in self._client.objects

    @property
    def _record_key(self) -> tuple[str, str]:
        return self.container_name, self.object_key

    def _record_for(self) -> dict[str, Any]:
        try:
            return self._client.objects[self._record_key]
        except KeyError as e:
            raise AzureProviderError("BlobNotFound", status_code=404) from e


async def chunks(*items: bytes) -> AsyncIterator[bytes]:
    for item in items:
        yield item


async def collect(stream: AsyncIterator[bytes]) -> bytes:
    body = bytearray()
    async for chunk in stream:
        body.extend(chunk)
    return bytes(body)
