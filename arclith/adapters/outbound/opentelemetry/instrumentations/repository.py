from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from uuid6 import UUID

from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.observability import MetricPort, TracePort
from arclith.domain.ports.outbound.repository import Repository

T = TypeVar("T", bound=Entity)
R = TypeVar("R")


class ObservedRepository(Repository[T]):
    """Observe repository operations without exporting entities or identifiers."""

    def __init__(
        self,
        repository: Repository[T],
        tracer: TracePort,
        metrics: MetricPort,
    ) -> None:
        self._repository = repository
        self._tracer = tracer
        self._metrics = metrics

    async def create(self, entity: T) -> T:
        return await self._observe("create", lambda: self._repository.create(entity))

    async def read(self, uuid: UUID) -> T | None:
        return await self._observe("read", lambda: self._repository.read(uuid))

    async def update(self, entity: T) -> T:
        return await self._observe("update", lambda: self._repository.update(entity))

    async def delete(self, uuid: UUID) -> None:
        await self._observe("delete", lambda: self._repository.delete(uuid))

    async def find_all(self) -> list[T]:
        return await self._observe("find_all", self._repository.find_all)

    async def find_page(
        self, offset: int = 0, limit: int | None = None
    ) -> tuple[list[T], int]:
        return await self._observe(
            "find_page", lambda: self._repository.find_page(offset, limit)
        )

    async def find_deleted(self) -> list[T]:
        return await self._observe("find_deleted", self._repository.find_deleted)

    async def duplicate(self, uuid: UUID) -> T:
        return await self._observe(
            "duplicate", lambda: self._repository.duplicate(uuid)
        )

    async def _observe(self, operation: str, call: Callable[[], Awaitable[R]]) -> R:
        started_at = time.perf_counter()
        attributes = {"db.operation.name": operation}
        try:
            with self._tracer.span(
                f"arclith.repository.{operation}",
                kind="client",
                metadata=attributes,
            ) as span:
                result = await call()
                span.set_outputs({"status": "success"})
        except BaseException as exc:
            self._record_metrics(started_at, operation, type(exc).__name__)
            raise
        self._record_metrics(started_at, operation, "none")
        return result

    def _record_metrics(
        self, started_at: float, operation: str, error_type: str
    ) -> None:
        attributes = {
            "db.operation.name": operation,
            "error.type": error_type,
        }
        self._metrics.add_counter(
            "arclith.repository.operations",
            attributes=attributes,
            description="Repository operations processed by Arclith",
        )
        self._metrics.record_histogram(
            "arclith.repository.duration",
            (time.perf_counter() - started_at) * 1000,
            attributes=attributes,
            description="Repository operation duration",
        )
