from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from arclith.adapters.outbound.filesystem import FilesystemFileStorage, FilesystemStorageConfig
from arclith.domain.ports.outbound.file_storage import (
    FileStorageConflict,
    FileStorageInvalidKey,
    FileStorageNotFound,
    FileStoragePermissionDenied,
    FileStorageUnavailable,
)


async def _chunks(*items: bytes) -> AsyncIterator[bytes]:
    for item in items:
        yield item


async def _collect(stream: AsyncIterator[bytes]) -> bytes:
    body = bytearray()
    async for chunk in stream:
        body.extend(chunk)
    return bytes(body)


@pytest.mark.asyncio
async def test_filesystem_file_storage_round_trips_file_and_metadata(tmp_path: Path) -> None:
    storage = FilesystemFileStorage(FilesystemStorageConfig(root_path=tmp_path, prefix="uploads"))

    stored = await storage.put(
        "tenant-a/docs/readme.txt",
        _chunks(b"", b"hello ", b"filesystem"),
        content_type="text/plain",
        metadata={"owner": "tenant-a"},
    )
    stream = await storage.get("tenant-a/docs/readme.txt")
    stat = await storage.stat("tenant-a/docs/readme.txt")

    assert stored.key == "tenant-a/docs/readme.txt"
    assert stored.size == 16
    assert stored.content_type == "text/plain"
    assert stored.checksum is not None
    assert stored.etag == stored.checksum
    assert stored.custom == {"owner": "tenant-a"}
    assert await _collect(stream.body) == b"hello filesystem"
    assert stream.metadata == stat
    assert stat.size == 16
    assert stat.content_type == "text/plain"
    assert stat.custom == {"owner": "tenant-a"}
    assert await storage.exists("tenant-a/docs/readme.txt") is True
    assert (tmp_path / "uploads" / "tenant-a" / "docs" / "readme.txt").read_bytes() == b"hello filesystem"
    assert (tmp_path / ".arclith-storage-metadata" / "tenant-a" / "docs" / "readme.txt.json").exists()


@pytest.mark.asyncio
async def test_filesystem_file_storage_delete_is_idempotent(tmp_path: Path) -> None:
    storage = FilesystemFileStorage(FilesystemStorageConfig(root_path=tmp_path))

    await storage.put("docs/readme.txt", _chunks(b"content"))
    await storage.delete("docs/readme.txt")
    await storage.delete("docs/readme.txt")

    assert await storage.exists("docs/readme.txt") is False
    with pytest.raises(FileStorageNotFound):
        await storage.stat("docs/readme.txt")


@pytest.mark.asyncio
async def test_filesystem_file_storage_overwrites_existing_file(tmp_path: Path) -> None:
    storage = FilesystemFileStorage(FilesystemStorageConfig(root_path=tmp_path))

    await storage.put("docs/readme.txt", _chunks(b"first"))
    stored = await storage.put("docs/readme.txt", _chunks(b"second"))
    stream = await storage.get("docs/readme.txt")

    assert stored.size == 6
    assert await _collect(stream.body) == b"second"


@pytest.mark.parametrize(
    "key",
    [
        "../secret.txt",
        "/etc/passwd",
        "folder/../secret.txt",
        "folder\\secret.txt",
        ".arclith-storage-metadata/readme.txt",
    ],
)
@pytest.mark.asyncio
async def test_filesystem_file_storage_rejects_unsafe_keys(tmp_path: Path, key: str) -> None:
    storage = FilesystemFileStorage(FilesystemStorageConfig(root_path=tmp_path))

    with pytest.raises(FileStorageInvalidKey):
        await storage.put(key, _chunks(b"blocked"))


def test_filesystem_file_storage_creates_root_when_configured(tmp_path: Path) -> None:
    root_path = tmp_path / "missing" / "files"

    FilesystemFileStorage(FilesystemStorageConfig(root_path=root_path, create_root=True))

    assert root_path.is_dir()


def test_filesystem_file_storage_rejects_missing_root_without_create(tmp_path: Path) -> None:
    root_path = tmp_path / "missing" / "files"

    with pytest.raises(FileStorageUnavailable, match="root"):
        FilesystemFileStorage(FilesystemStorageConfig(root_path=root_path, create_root=False))


def test_filesystem_file_storage_rejects_file_root(tmp_path: Path) -> None:
    root_path = tmp_path / "files"
    root_path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(FileStorageUnavailable, match="root"):
        FilesystemFileStorage(FilesystemStorageConfig(root_path=root_path))


def test_filesystem_file_storage_rejects_reserved_prefix(tmp_path: Path) -> None:
    with pytest.raises(FileStorageInvalidKey, match="reserved"):
        FilesystemFileStorage(
            FilesystemStorageConfig(root_path=tmp_path, prefix=".arclith-storage-metadata/public")
        )


@pytest.mark.asyncio
async def test_filesystem_file_storage_does_not_follow_symlink_outside_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root_path = tmp_path / "root"
    root_path.mkdir()
    (root_path / "escape").symlink_to(outside, target_is_directory=True)
    storage = FilesystemFileStorage(FilesystemStorageConfig(root_path=root_path))

    with pytest.raises(FileStoragePermissionDenied, match="escapes root") as exc_info:
        await storage.put("escape/secret.txt", _chunks(b"blocked"))

    assert str(root_path) not in str(exc_info.value)
    assert str(outside) not in str(exc_info.value)
    assert not (outside / "secret.txt").exists()


@pytest.mark.asyncio
async def test_filesystem_file_storage_rejects_directory_object_path(tmp_path: Path) -> None:
    storage = FilesystemFileStorage(FilesystemStorageConfig(root_path=tmp_path))
    (tmp_path / "docs").mkdir()

    with pytest.raises(FileStorageConflict):
        await storage.stat("docs")

    assert await storage.exists("docs") is False


@pytest.mark.asyncio
async def test_filesystem_file_storage_rejects_delete_directory_object_path(tmp_path: Path) -> None:
    storage = FilesystemFileStorage(FilesystemStorageConfig(root_path=tmp_path))
    (tmp_path / "docs").mkdir()

    with pytest.raises(FileStorageConflict, match="directory"):
        await storage.delete("docs")


@pytest.mark.asyncio
async def test_filesystem_file_storage_rejects_put_when_target_is_directory(tmp_path: Path) -> None:
    storage = FilesystemFileStorage(FilesystemStorageConfig(root_path=tmp_path))
    (tmp_path / "docs").mkdir()

    with pytest.raises(FileStorageConflict, match="directory"):
        await storage.put("docs", _chunks(b"blocked"))

    assert not list(tmp_path.glob(".arclith-*.tmp"))


@pytest.mark.asyncio
async def test_filesystem_file_storage_rejects_file_parent_path(tmp_path: Path) -> None:
    storage = FilesystemFileStorage(FilesystemStorageConfig(root_path=tmp_path))
    (tmp_path / "docs").write_text("not a directory", encoding="utf-8")

    with pytest.raises(FileStorageConflict, match="parent"):
        await storage.put("docs/readme.txt", _chunks(b"blocked"))


@pytest.mark.asyncio
async def test_filesystem_file_storage_stat_without_metadata_sidecar(tmp_path: Path) -> None:
    storage = FilesystemFileStorage(FilesystemStorageConfig(root_path=tmp_path))
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "readme.txt").write_text("raw", encoding="utf-8")

    stat = await storage.stat("docs/readme.txt")

    assert stat.size == 3
    assert stat.content_type is None
    assert stat.checksum is None
    assert stat.etag is None
    assert stat.custom == {}


@pytest.mark.asyncio
async def test_filesystem_file_storage_rejects_invalid_metadata_sidecar(tmp_path: Path) -> None:
    storage = FilesystemFileStorage(FilesystemStorageConfig(root_path=tmp_path))
    await storage.put("docs/readme.txt", _chunks(b"content"))
    (tmp_path / ".arclith-storage-metadata" / "docs" / "readme.txt.json").write_text("{", encoding="utf-8")

    with pytest.raises(FileStorageUnavailable, match="metadata"):
        await storage.stat("docs/readme.txt")


@pytest.mark.asyncio
async def test_filesystem_file_storage_ignores_malformed_metadata_payload(tmp_path: Path) -> None:
    storage = FilesystemFileStorage(FilesystemStorageConfig(root_path=tmp_path))
    await storage.put("docs/list.txt", _chunks(b"list"))
    await storage.put("docs/types.txt", _chunks(b"types"))
    metadata_root = tmp_path / ".arclith-storage-metadata" / "docs"
    (metadata_root / "list.txt.json").write_text("[]", encoding="utf-8")
    (metadata_root / "types.txt.json").write_text(
        '{"content_type": 42, "checksum": 42, "etag": 42, "custom": "bad"}',
        encoding="utf-8",
    )

    list_stat = await storage.stat("docs/list.txt")
    types_stat = await storage.stat("docs/types.txt")

    assert list_stat.content_type is None
    assert list_stat.custom == {}
    assert types_stat.content_type is None
    assert types_stat.checksum is None
    assert types_stat.etag is None
    assert types_stat.custom == {}


@pytest.mark.asyncio
async def test_filesystem_file_storage_wraps_metadata_write_errors(tmp_path: Path) -> None:
    storage = FilesystemFileStorage(FilesystemStorageConfig(root_path=tmp_path))
    metadata_path = tmp_path / ".arclith-storage-metadata" / "docs" / "readme.txt.json"
    metadata_path.mkdir(parents=True)

    with pytest.raises(FileStorageUnavailable, match="metadata write") as exc_info:
        await storage.put("docs/readme.txt", _chunks(b"content"))

    assert str(tmp_path) not in str(exc_info.value)


@pytest.mark.asyncio
async def test_filesystem_file_storage_read_reports_missing_file(tmp_path: Path) -> None:
    storage = FilesystemFileStorage(FilesystemStorageConfig(root_path=tmp_path))
    await storage.put("docs/readme.txt", _chunks(b"content"))
    stream = await storage.get("docs/readme.txt")
    (tmp_path / "docs" / "readme.txt").unlink()

    with pytest.raises(FileStorageNotFound):
        await _collect(stream.body)
