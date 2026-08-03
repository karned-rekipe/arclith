from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.logger import Logger
from arclith.domain.ports.outbound.repository import Repository
from arclith.infrastructure.config import AppConfig

T = TypeVar("T", bound=Entity)

AdapterFactory = Callable[[AppConfig, Logger], Repository[T]]


class AdapterRegistry(Generic[T]):
    """Registry mapping adapter names to factory functions.

    Usage::

        registry: AdapterRegistry[MyEntity] = (
            AdapterRegistry()
            .register("memory", lambda cfg, log: InMemoryMyEntityRepository())
            .register("mongodb", lambda cfg, log: MongoDBMyEntityRepository(...))
        )

        repo = registry.build(config, logger)
    """

    def __init__(self) -> None:
        self._factories: dict[str, AdapterFactory[T]] = {}

    def register(self, name: str, factory: AdapterFactory[T]) -> "AdapterRegistry[T]":
        self._factories[name] = factory
        return self

    def build(self, config: AppConfig, logger: Logger) -> Repository[T]:
        name = config.adapters.repository
        if name not in self._factories:
            available = sorted(self._factories)
            raise ValueError(
                f"Adapter '{name}' not registered. "
                f"Available: {available}. "
                "Register it via AdapterRegistry.register()."
            )
        return self._factories[name](config, logger)

