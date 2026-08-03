from __future__ import annotations

from collections.abc import Callable
from typing import Any
from typing import Generic
from typing import TypeVar
from typing import overload

from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.logger import Logger
from arclith.domain.ports.outbound.repository import Repository
from arclith.infrastructure.config import AppConfig

T = TypeVar("T", bound=Entity)
R = TypeVar("R", bound=Repository[Any])

RepositoryFactory = Callable[[AppConfig, type[T], Logger], R]


class RepositoryRegistry(Generic[T, R]):
    """Registry mapping repository adapter names to entity-aware factories."""

    def __init__(self) -> None:
        self._factories: dict[str, RepositoryFactory[T, R]] = {}

    def register(self, name: str, factory: RepositoryFactory[T, R]) -> "RepositoryRegistry[T, R]":
        self._factories[name] = factory
        return self

    def build(self, config: AppConfig, entity_class: type[T], logger: Logger) -> R:
        name = config.adapters.repository
        if name not in self._factories:
            raise ValueError(
                f"Repository adapter '{name}' not registered. "
                f"Available: {sorted(self._factories)}."
            )
        return self._factories[name](config, entity_class, logger)


@overload
def build_repository(
    config: AppConfig,
    entity_class: type[T],
    logger: Logger,
    *,
    registry: None = None,
) -> Repository[T]:
    pass


@overload
def build_repository(
    config: AppConfig,
    entity_class: type[T],
    logger: Logger,
    *,
    registry: RepositoryRegistry[T, R],
) -> R:
    pass


def build_repository(
    config: AppConfig,
    entity_class: type[T],
    logger: Logger,
    *,
    registry: RepositoryRegistry[T, R] | None = None,
) -> Repository[T] | R:
    if registry is None:
        return default_repository_registry(entity_class).build(config, entity_class, logger)
    return registry.build(config, entity_class, logger)


def default_repository_registry(_entity_class: type[T]) -> RepositoryRegistry[T, Repository[T]]:
    return (
        RepositoryRegistry[T, Repository[T]]()
        .register("memory", _build_memory_repository)
        .register("mongodb", _build_mongodb_repository)
        .register("duckdb", _build_duckdb_repository)
    )


def _build_memory_repository(
    _config: AppConfig,
    _entity_class: type[T],
    _logger: Logger,
) -> Repository[T]:
    from arclith.adapters.outbound.memory.repository import InMemoryRepository

    return InMemoryRepository()


def _build_mongodb_repository(
    config: AppConfig,
    entity_class: type[T],
    logger: Logger,
) -> Repository[T]:
    from arclith.adapters.outbound.mongodb.config import MongoDBConfig
    from arclith.adapters.outbound.mongodb.repository import MongoDBRepository

    mongo = config.adapters.mongodb
    if mongo is None:
        raise ValueError("MongoDB settings are required when repository=mongodb")

    return MongoDBRepository(
        MongoDBConfig(
            uri=mongo.uri,
            db_name=mongo.db_name,
            collection_name=mongo.collection_name,
        ),
        entity_class,
        logger,
    )


def _build_duckdb_repository(
    config: AppConfig,
    entity_class: type[T],
    _logger: Logger,
) -> Repository[T]:
    from arclith.adapters.outbound.duckdb.repository import DuckDBRepository

    duckdb = config.adapters.duckdb
    if duckdb is None:
        raise ValueError("DuckDB settings are required when repository=duckdb")

    return DuckDBRepository(duckdb.path, entity_class)
