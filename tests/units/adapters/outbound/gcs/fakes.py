from collections.abc import AsyncIterator
from datetime import UTC, datetime
from io import BytesIO
from typing import Any


class GCSProviderError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(str(code))
        self.code = code


class CloseTrackingBody(BytesIO):
    def __init__(self, initial_bytes: bytes) -> None:
        super().__init__(initial_bytes)
        self.adapter_closed = False

    def close(self) -> None:
        self.adapter_closed = True
        super().close()


class FailingBody:
    def __init__(self) -> None:
        self.closed = False

    def read(self, _size: int) -> bytes:
        raise GCSProviderError(403)

    def close(self) -> None:
        self.closed = True


class FakeGCSClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        self.errors: dict[str, Exception] = {}
        self.open_bodies: dict[tuple[str, str], Any] = {}
        self.last_body: CloseTrackingBody | None = None

    def bucket(self, bucket_name: str) -> "FakeGCSBucket":
        return FakeGCSBucket(self, bucket_name)

    def fail(self, operation: str, error: Exception) -> None:
        self.errors[operation] = error

    def _raise_if_needed(self, operation: str) -> None:
        error = self.errors.get(operation)
        if error is not None:
            raise error


class FakeGCSBucket:
    def __init__(self, client: FakeGCSClient, bucket_name: str) -> None:
        self._client = client
        self._bucket_name = bucket_name

    def blob(self, object_key: str) -> "FakeGCSBlob":
        return FakeGCSBlob(self._client, self._bucket_name, object_key)


class FakeGCSBlob:
    def __init__(
        self,
        client: FakeGCSClient,
        bucket_name: str,
        object_key: str,
    ) -> None:
        self._client = client
        self.bucket_name = bucket_name
        self.name = object_key
        self.metadata: dict[str, str] | None = None
        self.content_type: str | None = None
        self.size: int | None = None
        self.etag: str | None = None
        self.updated: datetime | None = None
        self.crc32c: str | None = None
        self.md5_hash: str | None = None
        self.generation: str | None = None
        self.metageneration: str | None = None

    def upload_from_file(
        self,
        file_obj: Any,
        *,
        rewind: bool = False,
        size: int | None = None,
        content_type: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._client._raise_if_needed("upload_from_file")
        if rewind:
            file_obj.seek(0)
        body = file_obj.read()
        record = {
            "Body": body,
            "content_type": content_type,
            "size": len(body),
            "etag": '"gcs-etag"',
            "updated": datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
            "crc32c": "provider-crc32c",
            "md5_hash": "provider-md5",
            "metadata": dict(self.metadata or {}),
            "generation": "1700000000000000",
            "metageneration": "1",
        }
        self._client.objects[self._record_key] = record
        self._sync_from_record(record)
        self._client.calls.append(
            (
                "upload_from_file",
                {
                    "bucket_name": self.bucket_name,
                    "object_key": self.name,
                    "rewind": rewind,
                    "size": size,
                    "content_type": content_type,
                    "metadata": dict(self.metadata or {}),
                    **kwargs,
                },
            )
        )

    def reload(self, **kwargs: Any) -> None:
        self._client._raise_if_needed("reload")
        self._client.calls.append(
            (
                "reload",
                {"bucket_name": self.bucket_name, "object_key": self.name, **kwargs},
            )
        )
        self._sync_from_record(self._record_for())

    def open(self, mode: str, **kwargs: Any) -> Any:
        self._client._raise_if_needed("open")
        self._client.calls.append(
            (
                "open",
                {
                    "bucket_name": self.bucket_name,
                    "object_key": self.name,
                    "mode": mode,
                    **kwargs,
                },
            )
        )
        self._record_for()
        override_body = self._client.open_bodies.get(self._record_key)
        if override_body is not None:
            return override_body
        record = self._client.objects[self._record_key]
        self._client.last_body = CloseTrackingBody(record["Body"])
        return self._client.last_body

    def delete(self, **kwargs: Any) -> None:
        self._client._raise_if_needed("delete")
        self._client.calls.append(
            (
                "delete",
                {"bucket_name": self.bucket_name, "object_key": self.name, **kwargs},
            )
        )
        self._record_for()
        self._client.objects.pop(self._record_key, None)

    def exists(self, **kwargs: Any) -> bool:
        self._client._raise_if_needed("exists")
        self._client.calls.append(
            (
                "exists",
                {"bucket_name": self.bucket_name, "object_key": self.name, **kwargs},
            )
        )
        return self._record_key in self._client.objects

    @property
    def _record_key(self) -> tuple[str, str]:
        return self.bucket_name, self.name

    def _record_for(self) -> dict[str, Any]:
        try:
            return self._client.objects[self._record_key]
        except KeyError as e:
            raise GCSProviderError(404) from e

    def _sync_from_record(self, record: dict[str, Any]) -> None:
        self.content_type = record["content_type"]
        self.size = record["size"]
        self.etag = record["etag"]
        self.updated = record["updated"]
        self.crc32c = record["crc32c"]
        self.md5_hash = record["md5_hash"]
        self.metadata = dict(record["metadata"])
        self.generation = record["generation"]
        self.metageneration = record["metageneration"]


async def chunks(*items: bytes) -> AsyncIterator[bytes]:
    for item in items:
        yield item


async def collect(stream: AsyncIterator[bytes]) -> bytes:
    body = bytearray()
    async for chunk in stream:
        body.extend(chunk)
    return bytes(body)
