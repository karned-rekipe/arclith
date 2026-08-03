from abc import ABC, abstractmethod
from typing import Generic, Optional, TypeVar

from uuid6 import UUID

from arclith.domain.models.entity import Entity

T = TypeVar("T", bound=Entity)


class Repository(ABC, Generic[T]):
    @abstractmethod
    async def create(self, entity: T) -> T:
        pass  # pragma: no cover

    @abstractmethod
    async def read(self, uuid: UUID) -> Optional[T]:
        pass  # pragma: no cover

    @abstractmethod
    async def update(self, entity: T) -> T:
        pass  # pragma: no cover

    @abstractmethod
    async def delete(self, uuid: UUID) -> None:
        pass  # pragma: no cover

    @abstractmethod
    async def find_all(self) -> list[T]:
        pass  # pragma: no cover

    @abstractmethod
    async def find_page(self, offset: int = 0, limit: int | None = None) -> tuple[list[T], int]:
        """Return a page of active entities and the total count (single query).

        Args:
            offset: Number of records to skip.
            limit:  Max records to return (None = all remaining).

        Returns:
            ``(items, total)`` where *total* is the full count matching the
            filter *before* offset/limit — suitable for pagination headers.
        """
        pass  # pragma: no cover

    @abstractmethod
    async def find_deleted(self) -> list[T]:
        pass  # pragma: no cover

    @abstractmethod
    async def duplicate(self, uuid: UUID) -> T:
        pass  # pragma: no cover
