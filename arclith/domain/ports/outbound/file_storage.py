from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath
from types import MappingProxyType


class FileStorageError(Exception):
    """Base error for file storage adapters."""

    def __init__(self, message: str, *, key: str | None = None) -> None:
        super().__init__(message)
        self.key = key


class FileStorageInvalidKey(FileStorageError):
    """Raised when an object key is empty, absolute, or attempts traversal."""


class FileStorageNotFound(FileStorageError):
    """Raised when an object does not exist."""


class FileStorageConflict(FileStorageError):
    """Raised when an object write conflicts with backend state."""


class FileStorageUnavailable(FileStorageError):
    """Raised when the backend is unavailable."""


class FileStoragePermissionDenied(FileStorageError):
    """Raised when credentials or backend policy reject the operation."""


@dataclass(frozen=True)
class StoredObjectMetadata:
    """Provider-neutral object metadata returned by storage adapters."""

    key: str
    content_type: str | None = None
    size: int | None = None
    checksum: str | None = None
    etag: str | None = None
    last_modified: datetime | None = None
    custom: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "custom", MappingProxyType(dict(self.custom)))


@dataclass(frozen=True)
class StoredObject(StoredObjectMetadata):
    """Metadata returned after a successful write."""


@dataclass(frozen=True)
class StoredObjectStream:
    """Object metadata plus an async byte stream."""

    metadata: StoredObjectMetadata
    body: AsyncIterator[bytes]


def normalize_storage_key(key: str) -> str:
    """Validate and return a relative POSIX object key."""
    if not key:
        raise FileStorageInvalidKey("storage key must not be empty", key=key)
    if key != key.strip():
        raise FileStorageInvalidKey("storage key must not contain surrounding whitespace", key=key)
    if "\\" in key:
        raise FileStorageInvalidKey("storage key must use POSIX '/' separators", key=key)
    if key.startswith("/") or key.endswith("/") or "//" in key:
        raise FileStorageInvalidKey("storage key must be a normalized relative path", key=key)

    parts = key.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise FileStorageInvalidKey("storage key must not contain empty, '.', or '..' segments", key=key)

    normalized = PurePosixPath(key).as_posix()
    if normalized != key:
        raise FileStorageInvalidKey("storage key must already be normalized", key=key)
    return normalized


class FileStoragePort(ABC):
    """Outbound port for binary object storage."""

    @abstractmethod
    async def put(
        self,
        key: str,
        content: AsyncIterator[bytes],
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        """Store object content and return provider-neutral metadata."""
        pass  # pragma: no cover

    @abstractmethod
    async def get(self, key: str) -> StoredObjectStream:
        """Return object metadata and an async byte stream."""
        pass  # pragma: no cover

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete an object if the backend accepts the operation."""
        pass  # pragma: no cover

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Return whether an object exists."""
        pass  # pragma: no cover

    @abstractmethod
    async def stat(self, key: str) -> StoredObjectMetadata:
        """Return metadata without downloading object content."""
        pass  # pragma: no cover
