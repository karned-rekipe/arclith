import subprocess
import sys
from collections.abc import Mapping
from typing import Any

import pytest

from arclith.adapters.outbound.memory.repository import InMemoryRepository
from arclith.adapters.outbound.relational import (
    RelationalColumn,
    RelationalMapperRegistry,
)
from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.repository import Repository
from arclith.infrastructure.config import (
    AppConfig,
    AdaptersSettings,
    DuckDBSettings,
    MariaDBSettings,
    MongoDBSettings,
    PostgreSQLSettings,
)
from arclith.infrastructure.repository_factory import (
    RepositoryRegistry,
    build_repository,
    default_repository_registry,
)


class Item(Entity):
    name: str = "item"


class ChatThread(Entity):
    pass


class UserAccount(Entity):
    pass


class ItemMapper:
    entity_class = Item
    table_name = "items"
    columns = (
        RelationalColumn("uuid", "uuid", primary_key=True),
        RelationalColumn("name", "string", indexed=True),
        RelationalColumn("created_at", "datetime", indexed=True),
        RelationalColumn("updated_at", "datetime"),
        RelationalColumn("deleted_at", "datetime", nullable=True, indexed=True),
        RelationalColumn("version", "integer"),
    )
    indexes = ()

    def to_record(self, entity: Item) -> Mapping[str, Any]:
        return {
            "uuid": entity.uuid,
            "name": entity.name,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
            "deleted_at": entity.deleted_at,
            "version": entity.version,
        }

    def from_record(self, record: Mapping[str, Any]) -> Item:
        return Item(**dict(record))


def _entity_path(entity_class: type[Entity]) -> str:
    return f"{entity_class.__module__}.{entity_class.__qualname__}"


def test_memory_returns_in_memory_repository(logger):
    config = AppConfig(adapters=AdaptersSettings(repository="memory"))
    repo = build_repository(config, Item, logger)
    assert isinstance(repo, InMemoryRepository)


def test_unknown_default_repository_adapter_raises(logger):
    config = AppConfig(adapters=AdaptersSettings(repository="customdb"))

    with pytest.raises(ValueError, match="customdb"):
        build_repository(config, Item, logger)


def test_custom_repository_registry_builds_unknown_adapter(logger):
    config = AppConfig(adapters=AdaptersSettings(repository="customdb"))
    expected = InMemoryRepository[Item]()
    registry = RepositoryRegistry[Item, Repository[Item]]().register(
        "customdb",
        lambda cfg, entity_class, log: expected,
    )

    repo = build_repository(config, Item, logger, registry=registry)

    assert repo is expected


def test_repository_registry_routes_each_entity_to_its_binding(logger):
    config = AppConfig(
        adapters=AdaptersSettings(
            repository="memory",
            repository_bindings={
                _entity_path(ChatThread): "mongodb",
                _entity_path(UserAccount): "mariadb",
            },
            mongodb=MongoDBSettings(db_name="chat_service"),
            mariadb=MariaDBSettings(database="identity_service"),
        )
    )
    chat_repository = InMemoryRepository[ChatThread]()
    user_repository = InMemoryRepository[UserAccount]()
    selected: list[tuple[str, type[Entity]]] = []

    def build_mongodb(config, entity_class, logger):
        selected.append(("mongodb", entity_class))
        return chat_repository

    def build_mariadb(config, entity_class, logger):
        selected.append(("mariadb", entity_class))
        return user_repository

    registry = (
        RepositoryRegistry()
        .register("mongodb", build_mongodb)
        .register("mariadb", build_mariadb)
    )

    assert (
        build_repository(config, ChatThread, logger, registry=registry)
        is chat_repository
    )
    assert (
        build_repository(config, UserAccount, logger, registry=registry)
        is user_repository
    )
    assert selected == [("mongodb", ChatThread), ("mariadb", UserAccount)]


def test_repository_registry_uses_global_fallback_for_unbound_entity(logger):
    config = AppConfig(
        adapters=AdaptersSettings(
            repository="memory",
            repository_bindings={_entity_path(ChatThread): "customdb"},
        )
    )
    expected = InMemoryRepository[UserAccount]()
    registry = RepositoryRegistry().register(
        "memory", lambda config, entity_class, logger: expected
    )

    repository = build_repository(config, UserAccount, logger, registry=registry)

    assert repository is expected


def test_repository_registry_rejects_unknown_bound_adapter(logger):
    config = AppConfig(
        adapters=AdaptersSettings(
            repository="memory",
            repository_bindings={_entity_path(ChatThread): "missing"},
        )
    )
    registry = RepositoryRegistry().register(
        "memory", lambda config, entity_class, logger: InMemoryRepository()
    )

    with pytest.raises(
        ValueError,
        match=rf"missing.*{_entity_path(ChatThread)}.*not registered",
    ):
        build_repository(config, ChatThread, logger, registry=registry)


def test_mongodb_returns_mongodb_repository(logger):
    pytest.importorskip("motor")
    from arclith.adapters.outbound.mongodb.repository import MongoDBRepository

    config = AppConfig(
        adapters=AdaptersSettings(
            repository="mongodb",
            mongodb=MongoDBSettings(db_name="test", collection_name="items"),
        )
    )
    repo = build_repository(config, Item, logger)
    assert isinstance(repo, MongoDBRepository)
    assert repo._config.uri is None
    assert repo._config.collection_name == "items"


def test_duckdb_returns_duckdb_repository(logger, tmp_path):
    pytest.importorskip("duckdb")
    from arclith.adapters.outbound.duckdb.repository import DuckDBRepository

    config = AppConfig(
        adapters=AdaptersSettings(
            repository="duckdb",
            duckdb=DuckDBSettings(path=str(tmp_path) + "/"),
        )
    )
    repo = build_repository(config, Item, logger)
    assert isinstance(repo, DuckDBRepository)


def test_mariadb_returns_mariadb_repository(logger):
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("asyncmy")
    from arclith.adapters.outbound.mariadb.repository import MariaDBRepository

    config = AppConfig(
        adapters=AdaptersSettings(
            repository="mariadb",
            mariadb=MariaDBSettings(database="test"),
        )
    )
    repo = build_repository(config, Item, logger)
    assert isinstance(repo, MariaDBRepository)


def test_postgresql_returns_postgresql_repository(logger):
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("asyncpg")
    from arclith.adapters.outbound.postgresql.repository import PostgreSQLRepository

    config = AppConfig(
        adapters=AdaptersSettings(
            repository="postgresql",
            postgresql=PostgreSQLSettings(database="test"),
        )
    )
    repo = build_repository(config, Item, logger)
    assert isinstance(repo, PostgreSQLRepository)
    assert repo._mapper is None
    assert repo._config.mapping_strategy == "generic_json"


def test_postgresql_structured_requires_registered_mapper(logger):
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("asyncpg")
    config = AppConfig(
        adapters=AdaptersSettings(
            repository="postgresql",
            postgresql=PostgreSQLSettings(
                database="test", mapping_strategy="structured"
            ),
        )
    )

    with pytest.raises(ValueError, match=r"registered mapper.*Item"):
        build_repository(config, Item, logger)


def test_postgresql_structured_uses_application_mapper_registry(logger):
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("asyncpg")
    from arclith.adapters.outbound.postgresql.repository import PostgreSQLRepository

    config = AppConfig(
        adapters=AdaptersSettings(
            repository="postgresql",
            postgresql=PostgreSQLSettings(
                database="test",
                mapping_strategy="structured",
                auto_create_schema=False,
            ),
        )
    )
    mapper = ItemMapper()
    mapper_registry = RelationalMapperRegistry().register(mapper)

    repo = build_repository(
        config,
        Item,
        logger,
        mapper_registry=mapper_registry,
    )

    assert isinstance(repo, PostgreSQLRepository)
    assert repo._mapper is mapper
    assert repo._config.auto_create_schema is False


def test_default_repository_registry_preserves_structured_mapper_wiring(logger):
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("asyncpg")
    config = AppConfig(
        adapters=AdaptersSettings(
            repository="postgresql",
            postgresql=PostgreSQLSettings(
                database="test", mapping_strategy="structured"
            ),
        )
    )
    mapper = ItemMapper()
    mapper_registry = RelationalMapperRegistry().register(mapper)
    repository_registry = default_repository_registry(
        Item,
        mapper_registry=mapper_registry,
    )

    repo = build_repository(config, Item, logger, registry=repository_registry)

    assert repo._mapper is mapper


def test_mapper_registry_cannot_be_combined_with_custom_repository_registry(logger):
    config = AppConfig(adapters=AdaptersSettings(repository="memory"))
    repository_registry = RepositoryRegistry().register(
        "memory", lambda config, entity_class, logger: InMemoryRepository()
    )

    with pytest.raises(ValueError, match="cannot be combined"):
        build_repository(
            config,
            Item,
            logger,
            registry=repository_registry,
            mapper_registry=RelationalMapperRegistry(),
        )


def test_import_arclith_does_not_require_sql_repository_extras():
    script = """
import importlib.abc
import sys


class BlockSQLRepositoryExtras(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "sqlalchemy" or fullname.startswith("sqlalchemy."):
            raise ModuleNotFoundError(fullname)
        if fullname == "asyncmy" or fullname.startswith("asyncmy."):
            raise ModuleNotFoundError(fullname)
        if fullname == "asyncpg" or fullname.startswith("asyncpg."):
            raise ModuleNotFoundError(fullname)
        return None


sys.meta_path.insert(0, BlockSQLRepositoryExtras())

import arclith
from arclith.domain.models.entity import Entity
from arclith.infrastructure.repository_factory import default_repository_registry


class SmokeItem(Entity):
    pass


default_repository_registry(SmokeItem)
print(arclith.__name__)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "arclith"
