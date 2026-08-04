from datetime import datetime, timedelta, timezone
from typing import Generic, TypeVar

from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.logger import Logger
from arclith.domain.ports.outbound.repository import Repository

T = TypeVar("T", bound=Entity)


class PurgeUseCase(Generic[T]):
    def __init__(self, repository: Repository[T], logger: Logger, retention_days: float | None = None) -> None:
        self._repository = repository
        self._logger = logger
        self._retention_days = retention_days

    async def execute(self) -> int:
        if self._retention_days is None:
            self._logger.info("⏭️ Purge skipped — retention is infinite")
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        expired = [
            e for e in await self._repository.find_deleted()
            if e.deleted_at is not None and e.deleted_at <= cutoff
        ]

        for entity in expired:
            await self._repository.delete(entity.uuid)

        self._logger.info("🧹 Purge complete", purged=len(expired), retention_days=self._retention_days)
        return len(expired)

