from __future__ import annotations

from collections.abc import Callable

from arclith.domain.ports.outbound.logger import Logger
from arclith.domain.ports.outbound.vector_store import VectorStorePort
from arclith.infrastructure.config import AppConfig

VectorStoreFactory = Callable[[AppConfig, Logger], VectorStorePort]


class VectorStoreRegistry:
    """Registry mapping vector-store adapter names to factories."""

    def __init__(self) -> None:
        self._factories: dict[str, VectorStoreFactory] = {}

    def register(self, name: str, factory: VectorStoreFactory) -> "VectorStoreRegistry":
        self._factories[name] = factory
        return self

    def build(self, config: AppConfig, logger: Logger) -> VectorStorePort:
        settings = config.adapters.vector_store
        if settings is None:
            raise ValueError(
                "adapters.vector_store is required to build a vector store"
            )
        if settings.adapter not in self._factories:
            raise ValueError(
                f"Vector-store adapter '{settings.adapter}' not registered. "
                f"Available: {sorted(self._factories)}."
            )
        return self._factories[settings.adapter](config, logger)


def build_vector_store(
    config: AppConfig,
    logger: Logger,
    *,
    registry: VectorStoreRegistry | None = None,
) -> VectorStorePort:
    active_registry = registry or default_vector_store_registry()
    return active_registry.build(config, logger)


def default_vector_store_registry() -> VectorStoreRegistry:
    return VectorStoreRegistry().register("memory", _build_memory_vector_store)


def _build_memory_vector_store(config: AppConfig, _logger: Logger) -> VectorStorePort:
    from arclith.adapters.outbound.memory.vector_store import MemoryVectorStore

    settings = config.adapters.vector_store
    if settings is None:
        raise ValueError("Memory vector-store settings are required")
    return MemoryVectorStore(settings)
