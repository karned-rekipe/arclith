import asyncio
import hashlib
import json
import tempfile
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arclith.domain.ports.outbound.file_storage import (
    FileStorageConflict,
    FileStorageInvalidKey,
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
_METADATA_ROOT = ".arclith-storage-metadata"


@dataclass(frozen=True)
class FilesystemStorageConfig:
    root_path: str | Path
    prefix: str = ""
    create_root: bool = True


class FilesystemFileStorage(FileStoragePort):
    """Filesystem implementation of the FileStoragePort contract."""

    def __init__(self, config: FilesystemStorageConfig) -> None:
        self._prefix = _normalize_optional_prefix(config.prefix)
        root_path = Path(config.root_path)
        self._root_path = self._prepare_directory(root_path, create=config.create_root)
        base_path = self._root_path / self._prefix if self._prefix else self._root_path
        if self._prefix and config.create_root:
            self._ensure_directory(base_path, base=self._root_path)
        self._base_path = self._prepare_directory(base_path, create=False)
        self._metadata_root = self._root_path / _METADATA_ROOT

    async def put(
        self,
        key: str,
        content: AsyncIterator[bytes],
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        normalized_key = _normalize_filesystem_key(key)
        target_path = self._target_path(normalized_key)
        self._ensure_parent_directory(target_path.parent)

        digest = hashlib.sha256()
        size = 0
        try:
            tmp_path = self._temporary_path(target_path.parent)
            try:
                with tmp_path.open("wb") as file:
                    async for chunk in content:
                        if not chunk:
                            continue
                        digest.update(chunk)
                        size += len(chunk)
                        await asyncio.to_thread(file.write, chunk)
                    await asyncio.to_thread(file.flush)
                self._replace_file(tmp_path, target_path, normalized_key)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
        except PermissionError as e:
            raise FileStoragePermissionDenied("filesystem storage write is not permitted", key=normalized_key) from e
        except OSError as e:
            raise FileStorageUnavailable("filesystem storage write failed", key=normalized_key) from e

        checksum = f"sha256:{digest.hexdigest()}"
        stat = self._file_stat(target_path, normalized_key)
        stored = StoredObject(
            key=normalized_key,
            content_type=content_type,
            size=size,
            checksum=checksum,
            etag=checksum,
            last_modified=datetime.fromtimestamp(stat.st_mtime, UTC),
            custom=dict(metadata or {}),
        )
        self._write_metadata(stored)
        return stored

    async def get(self, key: str) -> StoredObjectStream:
        metadata = await self.stat(key)
        path = self._existing_object_path(metadata.key)
        return StoredObjectStream(metadata=metadata, body=self._read_file(path, metadata.key))

    async def delete(self, key: str) -> None:
        normalized_key = _normalize_filesystem_key(key)
        path = self._target_path(normalized_key)
        if path.exists():
            self._assert_contained(path, normalized_key)
            if path.is_dir():
                raise FileStorageConflict("filesystem storage object path is a directory", key=normalized_key)
            try:
                path.unlink()
            except PermissionError as e:
                raise FileStoragePermissionDenied("filesystem storage delete is not permitted", key=normalized_key) from e
            except OSError as e:
                raise FileStorageUnavailable("filesystem storage delete failed", key=normalized_key) from e

        metadata_path = self._metadata_path(normalized_key)
        if metadata_path.exists():
            self._assert_contained(metadata_path, normalized_key)
            try:
                metadata_path.unlink()
            except PermissionError as e:
                raise FileStoragePermissionDenied("filesystem storage metadata delete is not permitted", key=normalized_key) from e
            except OSError as e:
                raise FileStorageUnavailable("filesystem storage metadata delete failed", key=normalized_key) from e

    async def exists(self, key: str) -> bool:
        normalized_key = _normalize_filesystem_key(key)
        path = self._target_path(normalized_key)
        if not path.exists():
            return False
        self._assert_contained(path, normalized_key)
        return path.is_file()

    async def stat(self, key: str) -> StoredObjectMetadata:
        normalized_key = _normalize_filesystem_key(key)
        path = self._existing_object_path(normalized_key)
        stat = self._file_stat(path, normalized_key)
        metadata = self._load_metadata(normalized_key)
        return StoredObjectMetadata(
            key=normalized_key,
            content_type=metadata.get("content_type"),
            size=stat.st_size,
            checksum=metadata.get("checksum"),
            etag=metadata.get("etag"),
            last_modified=datetime.fromtimestamp(stat.st_mtime, UTC),
            custom=metadata.get("custom", {}),
        )

    def _target_path(self, normalized_key: str) -> Path:
        return self._base_path / normalized_key

    def _existing_object_path(self, normalized_key: str) -> Path:
        path = self._target_path(normalized_key)
        if not path.exists():
            raise FileStorageNotFound("filesystem storage object not found", key=normalized_key)
        self._assert_contained(path, normalized_key)
        if not path.is_file():
            raise FileStorageConflict("filesystem storage object path is not a file", key=normalized_key)
        return path

    def _prepare_directory(self, path: Path, *, create: bool) -> Path:
        try:
            if create:
                path.mkdir(parents=True, exist_ok=True)
            if not path.exists() or not path.is_dir():
                raise FileStorageUnavailable("filesystem storage root is unavailable")
        except PermissionError as e:
            raise FileStoragePermissionDenied("filesystem storage root is not writable") from e
        except OSError as e:
            raise FileStorageUnavailable("filesystem storage root is unavailable") from e

        try:
            resolved = path.resolve()
        except PermissionError as e:
            raise FileStoragePermissionDenied("filesystem storage root is not readable") from e
        except OSError as e:
            raise FileStorageUnavailable("filesystem storage root is unavailable") from e
        if hasattr(self, "_root_path") and resolved != self._root_path:
            self._assert_path_inside(resolved, self._root_path)
        return resolved

    def _ensure_parent_directory(self, parent: Path, *, base: Path | None = None) -> None:
        base_path = base or self._base_path
        self._ensure_directory(parent, base=base_path)

    def _ensure_directory(self, directory: Path, *, base: Path) -> None:
        relative_parent = directory.relative_to(base)
        current = base
        for part in relative_parent.parts:
            current = current / part
            if current.exists():
                self._assert_directory(current)
            else:
                try:
                    current.mkdir(exist_ok=True)
                    self._assert_directory(current)
                except FileExistsError as e:
                    raise FileStorageConflict("filesystem storage parent path is not a directory") from e
                except PermissionError as e:
                    raise FileStoragePermissionDenied("filesystem storage parent is not writable") from e
                except OSError as e:
                    raise FileStorageUnavailable("filesystem storage parent is unavailable") from e

    def _assert_directory(self, path: Path) -> None:
        self._assert_contained(path, None)
        if not path.is_dir():
            raise FileStorageConflict("filesystem storage parent path is not a directory")

    def _temporary_path(self, parent: Path) -> Path:
        with tempfile.NamedTemporaryFile(prefix=".arclith-", suffix=".tmp", dir=parent, delete=False) as file:
            return Path(file.name)

    def _replace_file(self, tmp_path: Path, target_path: Path, key: str) -> None:
        if target_path.exists():
            self._assert_contained(target_path, key)
            if target_path.is_dir():
                raise FileStorageConflict("filesystem storage object path is a directory", key=key)
        tmp_path.replace(target_path)

    def _file_stat(self, path: Path, key: str) -> Any:
        try:
            return path.stat()
        except FileNotFoundError:
            raise FileStorageNotFound("filesystem storage object not found", key=key) from None
        except PermissionError as e:
            raise FileStoragePermissionDenied("filesystem storage object is not readable", key=key) from e
        except OSError as e:
            raise FileStorageUnavailable("filesystem storage stat failed", key=key) from e

    async def _read_file(self, path: Path, key: str) -> AsyncIterator[bytes]:
        try:
            with path.open("rb") as file:
                while True:
                    chunk = await asyncio.to_thread(file.read, _CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk
        except FileNotFoundError:
            raise FileStorageNotFound("filesystem storage object not found", key=key) from None
        except PermissionError as e:
            raise FileStoragePermissionDenied("filesystem storage object is not readable", key=key) from e
        except OSError as e:
            raise FileStorageUnavailable("filesystem storage read failed", key=key) from e

    def _metadata_path(self, normalized_key: str) -> Path:
        return self._metadata_root / f"{normalized_key}.json"

    def _load_metadata(self, normalized_key: str) -> dict[str, Any]:
        metadata_path = self._metadata_path(normalized_key)
        if not metadata_path.exists():
            return {}
        self._assert_contained(metadata_path, normalized_key)
        raw_content = self._read_metadata_content(metadata_path, normalized_key)
        if raw_content is None:
            return {}

        try:
            return _normalize_metadata_payload(json.loads(raw_content))
        except json.JSONDecodeError as e:
            raise FileStorageUnavailable("filesystem storage metadata is invalid", key=normalized_key) from e

    def _read_metadata_content(self, metadata_path: Path, normalized_key: str) -> str | None:
        try:
            return metadata_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except PermissionError as e:
            raise FileStoragePermissionDenied("filesystem storage metadata is not readable", key=normalized_key) from e
        except OSError as e:
            raise FileStorageUnavailable("filesystem storage metadata read failed", key=normalized_key) from e

    def _write_metadata(self, metadata: StoredObjectMetadata) -> None:
        metadata_path = self._metadata_path(metadata.key)
        self._ensure_parent_directory(metadata_path.parent, base=self._root_path)
        payload = {
            "content_type": metadata.content_type,
            "checksum": metadata.checksum,
            "etag": metadata.etag,
            "custom": dict(metadata.custom),
        }
        try:
            tmp_path = self._temporary_path(metadata_path.parent)
            try:
                tmp_path.write_text(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    encoding="utf-8",
                )
                tmp_path.replace(metadata_path)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
        except PermissionError as e:
            raise FileStoragePermissionDenied("filesystem storage metadata write is not permitted", key=metadata.key) from e
        except OSError as e:
            raise FileStorageUnavailable("filesystem storage metadata write failed", key=metadata.key) from e

    def _assert_contained(self, path: Path, key: str | None) -> None:
        if not path.exists():
            return
        try:
            resolved = path.resolve()
        except PermissionError as e:
            raise FileStoragePermissionDenied("filesystem storage path is not readable", key=key) from e
        except OSError as e:
            raise FileStorageUnavailable("filesystem storage path cannot be resolved", key=key) from e
        self._assert_path_inside(resolved, self._root_path, key=key)

    def _assert_path_inside(self, path: Path, root: Path, *, key: str | None = None) -> None:
        if not path.is_relative_to(root):
            raise FileStoragePermissionDenied("filesystem storage path escapes root", key=key)


def _normalize_optional_prefix(prefix: str) -> str:
    if not prefix:
        return ""
    normalized = normalize_storage_key(prefix)
    if normalized == _METADATA_ROOT or normalized.startswith(f"{_METADATA_ROOT}/"):
        raise FileStorageInvalidKey("filesystem storage prefix is reserved", key=prefix)
    return normalized


def _normalize_filesystem_key(key: str) -> str:
    normalized = normalize_storage_key(key)
    if normalized == _METADATA_ROOT or normalized.startswith(f"{_METADATA_ROOT}/"):
        raise FileStorageInvalidKey("filesystem storage key uses reserved metadata prefix", key=key)
    return normalized


def _normalize_metadata_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}

    custom_raw = raw.get("custom", {})
    custom = custom_raw if isinstance(custom_raw, dict) else {}
    return {
        "content_type": _metadata_string(raw, "content_type"),
        "checksum": _metadata_string(raw, "checksum"),
        "etag": _metadata_string(raw, "etag"),
        "custom": {str(k): str(v) for k, v in custom.items() if isinstance(k, str) and isinstance(v, str)},
    }


def _metadata_string(raw: Mapping[str, Any], field: str) -> str | None:
    value = raw.get(field)
    if isinstance(value, str):
        return value
    return None
