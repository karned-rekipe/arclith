from datetime import datetime, timezone
from typing import Generic, TypeVar

from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.logger import Logger
from arclith.domain.ports.outbound.repository import Repository

T = TypeVar("T", bound=Entity)


class UpdateUseCase(Generic[T]):
    def __init__(self, repository: Repository[T], logger: Logger) -> None:
        self._repository = repository
        self._logger = logger

    async def execute(self, entity: T) -> T:
        entity = entity.model_copy(update={
            "updated_at": datetime.now(timezone.utc),
            "version": entity.version + 1,
        })
        self._logger.info("✏️ Updating entity", type=type(entity).__name__, uuid=str(entity.uuid))
        result = await self._repository.update(entity)
        self._logger.info("✅ Entity updated", type=type(result).__name__, uuid=str(result.uuid))
        return result

