import subprocess
import sys

import pytest

from arclith.adapters.outbound.memory.repository import InMemoryRepository
from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.repository import Repository
from arclith.infrastructure.config import AppConfig, AdaptersSettings, DuckDBSettings, MariaDBSettings, MongoDBSettings
from arclith.infrastructure.repository_factory import RepositoryRegistry, build_repository


class Item(Entity):
    name: str = "item"


def test_memory_returns_in_memory_repository(logger):
    config = AppConfig(adapters = AdaptersSettings(repository = "memory"))
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


def test_mongodb_returns_mongodb_repository(logger):
    pytest.importorskip("motor")
    from arclith.adapters.outbound.mongodb.repository import MongoDBRepository
    config = AppConfig(adapters = AdaptersSettings(
        repository = "mongodb",
        mongodb = MongoDBSettings(db_name = "test", collection_name = "items"),
    ))
    repo = build_repository(config, Item, logger)
    assert isinstance(repo, MongoDBRepository)
    assert repo._config.uri is None
    assert repo._config.collection_name == "items"


def test_duckdb_returns_duckdb_repository(logger, tmp_path):
    pytest.importorskip("duckdb")
    from arclith.adapters.outbound.duckdb.repository import DuckDBRepository
    config = AppConfig(adapters = AdaptersSettings(
        repository = "duckdb",
        duckdb = DuckDBSettings(path = str(tmp_path) + "/"),
    ))
    repo = build_repository(config, Item, logger)
    assert isinstance(repo, DuckDBRepository)


def test_mariadb_returns_mariadb_repository(logger):
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("asyncmy")
    from arclith.adapters.outbound.mariadb.repository import MariaDBRepository

    config = AppConfig(adapters=AdaptersSettings(
        repository="mariadb",
        mariadb=MariaDBSettings(database="test"),
    ))
    repo = build_repository(config, Item, logger)
    assert isinstance(repo, MariaDBRepository)


def test_import_arclith_does_not_require_mariadb_extra():
    script = """
import importlib.abc
import sys


class BlockMariaDBExtras(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "sqlalchemy" or fullname.startswith("sqlalchemy."):
            raise ModuleNotFoundError(fullname)
        if fullname == "asyncmy" or fullname.startswith("asyncmy."):
            raise ModuleNotFoundError(fullname)
        return None


sys.meta_path.insert(0, BlockMariaDBExtras())

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
