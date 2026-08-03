from datetime import datetime, timezone
from typing import Generic, TypeVar

from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.logger import Logger
from arclith.domain.ports.outbound.repository import Repository

T = TypeVar("T", bound=Entity)


class CreateUseCase(Generic[T]):
    def __init__(self, repository: Repository[T], logger: Logger) -> None:
        self._repository = repository
        self._logger = logger

    async def execute(self, entity: T) -> T:
        now = datetime.now(timezone.utc)
        entity = entity.model_copy(update={"created_at": now, "updated_at": now})
        self._logger.info("➕ Creating entity", type=type(entity).__name__, uuid=str(entity.uuid))
        result = await self._repository.create(entity)
        self._logger.info("✅ Entity created", type=type(result).__name__, uuid=str(result.uuid))
        return result

