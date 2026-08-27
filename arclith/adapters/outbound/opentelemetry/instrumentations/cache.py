from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from arclith.domain.ports.outbound.cache import CachePort
from arclith.domain.ports.outbound.observability import MetricPort, TracePort

R = TypeVar("R")


class ObservedCache(CachePort):
    """Observe cache operations without exporting keys or cached values."""

    def __init__(
        self,
        cache: CachePort,
        tracer: TracePort,
        metrics: MetricPort,
    ) -> None:
        self._cache = cache
        self._tracer = tracer
        self._metrics = metrics

    async def get(self, key: str) -> str | None:
        result = await self._observe("get", lambda: self._cache.get(key))
        self._metrics.add_counter(
            "arclith.cache.requests",
            attributes={
                "cache.operation.name": "get",
                "cache.result": "hit" if result is not None else "miss",
            },
            description="Cache requests processed by Arclith",
        )
        return result

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        await self._observe("set", lambda: self._cache.set(key, value, ttl_s))

    async def delete(self, key: str) -> None:
        await self._observe("delete", lambda: self._cache.delete(key))

    async def _observe(self, operation: str, call: Callable[[], Awaitable[R]]) -> R:
        started_at = time.perf_counter()
        try:
            with self._tracer.span(
                f"arclith.cache.{operation}",
                kind="client",
                metadata={"cache.operation.name": operation},
            ) as span:
                result = await call()
                span.set_outputs({"status": "success"})
        except BaseException as exc:
            self._record_duration(started_at, operation, type(exc).__name__)
            raise
        self._record_duration(started_at, operation, "none")
        return result

    def _record_duration(
        self, started_at: float, operation: str, error_type: str
    ) -> None:
        self._metrics.record_histogram(
            "arclith.cache.duration",
            (time.perf_counter() - started_at) * 1000,
            attributes={
                "cache.operation.name": operation,
                "error.type": error_type,
            },
            description="Cache operation duration",
        )
