import subprocess
import sys

import pytest

from arclith.adapters.outbound.memory.repository import InMemoryRepository
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
)


class Item(Entity):
    name: str = "item"


class ChatThread(Entity):
    pass


class UserAccount(Entity):
    pass


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
