from __future__ import annotations

from collections.abc import Callable
from typing import Generic
from typing import TypeVar

from arclith.domain.models.entity import Entity
from arclith.domain.ports.logger import Logger
from arclith.domain.ports.repository import Repository
from arclith.infrastructure.config import AppConfig

T = TypeVar("T", bound=Entity)

RepositoryFactory = Callable[[AppConfig, type[T], Logger], Repository[T]]


class RepositoryRegistry(Generic[T]):
    """Registry mapping repository adapter names to entity-aware factories."""

    def __init__(self) -> None:
        self._factories: dict[str, RepositoryFactory[T]] = {}

    def register(self, name: str, factory: RepositoryFactory[T]) -> "RepositoryRegistry[T]":
        self._factories[name] = factory
        return self

    def build(self, config: AppConfig, entity_class: type[T], logger: Logger) -> Repository[T]:
        name = config.adapters.repository
        if name not in self._factories:
            raise ValueError(
                f"Repository adapter '{name}' not registered. "
                f"Available: {sorted(self._factories)}."
            )
        return self._factories[name](config, entity_class, logger)


def build_repository(
    config: AppConfig,
    entity_class: type[T],
    logger: Logger,
    *,
    registry: RepositoryRegistry[T] | None = None,
) -> Repository[T]:
    selected_registry = registry if registry is not None else default_repository_registry()
    return selected_registry.build(config, entity_class, logger)


def default_repository_registry() -> RepositoryRegistry[T]:
    return (
        RepositoryRegistry[T]()
        .register("memory", _build_memory_repository)
        .register("mongodb", _build_mongodb_repository)
        .register("duckdb", _build_duckdb_repository)
    )


def _build_memory_repository(
    config: AppConfig,
    entity_class: type[T],
    logger: Logger,
) -> Repository[T]:
    from arclith.adapters.output.memory.repository import InMemoryRepository

    return InMemoryRepository()


def _build_mongodb_repository(
    config: AppConfig,
    entity_class: type[T],
    logger: Logger,
) -> Repository[T]:
    from arclith.adapters.output.mongodb.config import MongoDBConfig
    from arclith.adapters.output.mongodb.repository import MongoDBRepository

    mongo = config.adapters.mongodb
    if mongo is None:
        raise RuntimeError("MongoDB settings are required when repository=mongodb")

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
    logger: Logger,
) -> Repository[T]:
    from arclith.adapters.output.duckdb.repository import DuckDBRepository

    duckdb = config.adapters.duckdb
    if duckdb is None:
        raise RuntimeError("DuckDB settings are required when repository=duckdb")

    return DuckDBRepository(duckdb.path, entity_class)
