from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

import pytest

from arclith.domain.ports.outbound.file_storage import (
    FileStorageInvalidKey,
    FileStorageNotFound,
    FileStoragePort,
    StoredObject,
    StoredObjectMetadata,
    StoredObjectStream,
    normalize_storage_key,
)


async def _chunks(*items: bytes) -> AsyncIterator[bytes]:
    for item in items:
        yield item


async def _collect(stream: AsyncIterator[bytes]) -> bytes:
    body = bytearray()
    async for chunk in stream:
        body.extend(chunk)
    return bytes(body)


@dataclass(frozen=True)
class _StoredPayload:
    body: bytes
    metadata: StoredObjectMetadata


class InMemoryFileStorage(FileStoragePort):
    def __init__(self) -> None:
        self._objects: dict[str, _StoredPayload] = {}

    async def put(
        self,
        key: str,
        content: AsyncIterator[bytes],
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        normalized_key = normalize_storage_key(key)
        body = await _collect(content)
        object_metadata = StoredObjectMetadata(
            key=normalized_key,
            content_type=content_type,
            size=len(body),
            custom=dict(metadata or {}),
        )
        self._objects[normalized_key] = _StoredPayload(body=body, metadata=object_metadata)
        return StoredObject(
            key=object_metadata.key,
            content_type=object_metadata.content_type,
            size=object_metadata.size,
            custom=object_metadata.custom,
        )

    async def get(self, key: str) -> StoredObjectStream:
        payload = self._payload_for(key)
        return StoredObjectStream(metadata=payload.metadata, body=_chunks(payload.body))

    async def delete(self, key: str) -> None:
        normalized_key = normalize_storage_key(key)
        self._objects.pop(normalized_key, None)

    async def exists(self, key: str) -> bool:
        return normalize_storage_key(key) in self._objects

    async def stat(self, key: str) -> StoredObjectMetadata:
        return self._payload_for(key).metadata

    def _payload_for(self, key: str) -> _StoredPayload:
        normalized_key = normalize_storage_key(key)
        try:
            return self._objects[normalized_key]
        except KeyError:
            raise FileStorageNotFound("object not found", key=normalized_key) from None


def test_normalize_storage_key_accepts_relative_posix_keys() -> None:
    assert normalize_storage_key("tenant-a/invoices/2026-08.pdf") == "tenant-a/invoices/2026-08.pdf"


@pytest.mark.parametrize(
    "key",
    [
        "",
        " leading",
        "trailing ",
        "/absolute",
        "folder/",
        "folder//file.txt",
        "folder/./file.txt",
        "folder/../file.txt",
        "folder\\file.txt",
    ],
)
def test_normalize_storage_key_rejects_unsafe_keys(key: str) -> None:
    with pytest.raises(FileStorageInvalidKey) as exc_info:
        normalize_storage_key(key)

    assert getattr(exc_info.value, "key") == key


def test_stored_object_metadata_custom_is_immutable() -> None:
    custom = {"owner": "tenant-a"}

    metadata = StoredObjectMetadata(key="tenant-a/docs/readme.txt", custom=custom)
    custom["owner"] = "tenant-b"

    assert metadata.custom["owner"] == "tenant-a"
    with pytest.raises(TypeError):
        metadata.custom["owner"] = "tenant-c"  # type: ignore[index]


@pytest.mark.asyncio
async def test_file_storage_port_contract_round_trips_metadata_and_stream() -> None:
    storage = InMemoryFileStorage()

    stored = await storage.put(
        "tenant-a/docs/readme.txt",
        _chunks(b"hello ", b"storage"),
        content_type="text/plain",
        metadata={"owner": "tenant-a"},
    )
    stream = await storage.get("tenant-a/docs/readme.txt")
    stat = await storage.stat("tenant-a/docs/readme.txt")

    assert stored.key == "tenant-a/docs/readme.txt"
    assert stored.content_type == "text/plain"
    assert stored.size == 13
    assert stored.custom == {"owner": "tenant-a"}
    assert await _collect(stream.body) == b"hello storage"
    assert stream.metadata == stat
    assert await storage.exists("tenant-a/docs/readme.txt") is True


@pytest.mark.asyncio
async def test_file_storage_port_contract_raises_not_found_with_key() -> None:
    storage = InMemoryFileStorage()

    with pytest.raises(FileStorageNotFound) as exc_info:
        await storage.get("missing/object.bin")

    assert exc_info.value.key == "missing/object.bin"
