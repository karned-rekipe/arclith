from typing import Generic, Optional, TypeVar
from uuid6 import UUID

from arclith.application.timing import log_duration
from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.logger import Logger
from arclith.domain.ports.outbound.repository import Repository
from arclith.application.use_cases import (
    CreateUseCase,
    ReadUseCase,
    UpdateUseCase,
    DeleteUseCase,
    FindAllUseCase,
    DuplicateUseCase,
    PurgeUseCase,
)

T = TypeVar("T", bound=Entity)


class BaseService(Generic[T]):
    def __init__(self, repository: Repository[T], logger: Logger, retention_days: float | None = None) -> None:
        self._repository = repository
        self._logger = logger
        self._create_uc = CreateUseCase(repository, logger)
        self._read_uc = ReadUseCase(repository, logger)
        self._update_uc = UpdateUseCase(repository, logger)
        self._delete_uc = DeleteUseCase(repository, logger, retention_days)
        self._find_all_uc = FindAllUseCase(repository, logger)
        self._duplicate_uc = DuplicateUseCase(repository, logger)
        self._purge_uc = PurgeUseCase(repository, logger, retention_days)

    async def create(self, entity: T) -> T:
        async with log_duration(self._logger, "service.create"):
            return await self._create_uc.execute(entity)

    async def read(self, uuid: UUID) -> Optional[T]:
        async with log_duration(self._logger, "service.read"):
            return await self._read_uc.execute(uuid)

    async def update(self, entity: T) -> T:
        async with log_duration(self._logger, "service.update"):
            return await self._update_uc.execute(entity)

    async def delete(self, uuid: UUID, deleted_by: str | None = None) -> None:
        async with log_duration(self._logger, "service.delete"):
            await self._delete_uc.execute(uuid, deleted_by)

    async def find_all(self) -> list[T]:
        return await self._find_all_uc.execute()

    async def find_page(self, offset: int = 0, limit: int | None = None) -> tuple[list[T], int]:
        """Return a page of active entities and the total count."""
        async with log_duration(self._logger, "service.find_page", offset=offset, limit=limit):
            return await self._repository.find_page(offset, limit)

    async def duplicate(self, uuid: UUID) -> T:
        async with log_duration(self._logger, "service.duplicate"):
            return await self._duplicate_uc.execute(uuid)

    async def purge(self) -> int:
        return await self._purge_uc.execute()
