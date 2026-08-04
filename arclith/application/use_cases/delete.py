from datetime import datetime, timezone
from typing import Generic, TypeVar
from uuid6 import UUID

from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.logger import Logger
from arclith.domain.ports.outbound.repository import Repository

T = TypeVar("T", bound=Entity)


class DeleteUseCase(Generic[T]):
    def __init__(self, repository: Repository[T], logger: Logger, retention_days: float | None = None) -> None:
        self._repository = repository
        self._logger = logger
        self._retention_days = retention_days

    async def execute(self, uuid: UUID, deleted_by: str | None = None) -> None:
        if self._retention_days == 0:
            self._logger.info("🗑️ Hard deleting entity", uuid=str(uuid))
            await self._repository.delete(uuid)
            self._logger.info("✅ Entity hard deleted", uuid=str(uuid))
            return

        entity = await self._repository.read(uuid)
        if entity is None:
            self._logger.warning("⚠️ Entity not found for deletion", uuid=str(uuid))
            return

        now = datetime.now(timezone.utc)
        entity = entity.model_copy(update={"deleted_at": now, "deleted_by": deleted_by, "updated_at": now})
        await self._repository.update(entity)
        self._logger.info("🗑️ Entity soft deleted", uuid=str(uuid), retention_days=self._retention_days)

