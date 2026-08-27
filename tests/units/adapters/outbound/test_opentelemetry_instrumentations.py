from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from contextlib import contextmanager
from typing import Any

import pytest

from arclith.adapters.outbound.memory.cache_adapter import MemoryCacheAdapter
from arclith.adapters.outbound.memory.repository import InMemoryRepository
from arclith.adapters.outbound.opentelemetry.instrumentations.cache import (
    ObservedCache,
)
from arclith.adapters.outbound.opentelemetry.instrumentations.repository import (
    ObservedRepository,
)
from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.observability import (
    MetricPort,
    TracePort,
    TraceSpan,
)


class RecordingSpan(TraceSpan):
    def set_outputs(self, outputs: object | None) -> None:
        return None

    def set_metadata(self, metadata: Mapping[str, object]) -> None:
        return None


class RecordingTracer(TracePort):
    def __init__(self) -> None:
        self.names: list[str] = []

    @contextmanager
    def span(
        self,
        name: str,
        *,
        kind: str = "chain",
        inputs: object | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> Iterator[TraceSpan]:
        self.names.append(name)
        yield RecordingSpan()

    @contextmanager
    def context(
        self,
        *,
        enabled: bool | None = None,
        project: str | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, object] | None = None,
        parent: Mapping[str, str] | None = None,
    ) -> Iterator[None]:
        yield

    def inject(self, headers: MutableMapping[str, str]) -> None:
        return None

    def flush(self, timeout: float | None = None) -> None:
        return None

    def close(self, timeout: float | None = None) -> None:
        return None


class RecordingMetrics(MetricPort):
    def __init__(self) -> None:
        self.counters: list[tuple[str, Mapping[str, Any]]] = []
        self.histograms: list[tuple[str, Mapping[str, Any]]] = []

    def add_counter(
        self,
        name: str,
        value: int | float = 1,
        *,
        attributes: Mapping[str, str | bool | int | float] | None = None,
        description: str = "",
        unit: str = "1",
    ) -> None:
        self.counters.append((name, attributes or {}))

    def record_histogram(
        self,
        name: str,
        value: int | float,
        *,
        attributes: Mapping[str, str | bool | int | float] | None = None,
        description: str = "",
        unit: str = "ms",
    ) -> None:
        self.histograms.append((name, attributes or {}))


@pytest.mark.asyncio
async def test_observed_repository_never_adds_entity_or_uuid_attributes() -> None:
    tracer = RecordingTracer()
    metrics = RecordingMetrics()
    repository = ObservedRepository(InMemoryRepository(), tracer, metrics)
    entity = Entity()

    await repository.create(entity)
    assert await repository.read(entity.uuid) == entity

    assert tracer.names == ["arclith.repository.create", "arclith.repository.read"]
    assert all(
        set(attributes) <= {"db.operation.name", "error.type"}
        for _, attributes in [*metrics.counters, *metrics.histograms]
    )


@pytest.mark.asyncio
async def test_observed_cache_records_hit_miss_without_cache_key() -> None:
    tracer = RecordingTracer()
    metrics = RecordingMetrics()
    cache = ObservedCache(MemoryCacheAdapter(), tracer, metrics)

    assert await cache.get("secret:user:123") is None
    await cache.set("secret:user:123", "value", 60)
    assert await cache.get("secret:user:123") == "value"

    request_attributes = [
        attributes
        for name, attributes in metrics.counters
        if name == "arclith.cache.requests"
    ]
    assert request_attributes == [
        {"cache.operation.name": "get", "cache.result": "miss"},
        {"cache.operation.name": "get", "cache.result": "hit"},
    ]
    assert all("key" not in attributes for attributes in request_attributes)
