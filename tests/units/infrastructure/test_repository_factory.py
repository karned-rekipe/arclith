import pytest

from arclith.adapters.outbound.memory.repository import InMemoryRepository
from arclith.domain.models.entity import Entity
from arclith.domain.ports.outbound.repository import Repository
from arclith.infrastructure.config import AppConfig, AdaptersSettings, MongoDBSettings, DuckDBSettings
from arclith.infrastructure.repository_factory import RepositoryRegistry, build_repository


class Item(Entity):
    name: str = "item"


def test_memory_returns_in_memory_repository(logger):
    config = AppConfig(adapters = AdaptersSettings(repository = "memory"))
    repo = build_repository(config, Item, logger)
    assert isinstance(repo, InMemoryRepository)


def test_unknown_default_repository_adapter_raises(logger):
    config = AppConfig(adapters=AdaptersSettings(repository="mariadb"))

    with pytest.raises(ValueError, match="mariadb"):
        build_repository(config, Item, logger)


def test_custom_repository_registry_builds_unknown_adapter(logger):
    config = AppConfig(adapters=AdaptersSettings(repository="mariadb"))
    expected = InMemoryRepository[Item]()
    registry = RepositoryRegistry[Item, Repository[Item]]().register(
        "mariadb",
        lambda cfg, entity_class, log: expected,
    )

    repo = build_repository(config, Item, logger, registry=registry)

    assert repo is expected


def test_mongodb_returns_mongodb_repository(logger):
    pytest.importorskip("motor")
    from arclith.adapters.outbound.mongodb.repository import MongoDBRepository
    config = AppConfig(adapters = AdaptersSettings(
        repository = "mongodb",
        mongodb = MongoDBSettings(uri = "mongodb://localhost:27017", db_name = "test"),
    ))
    repo = build_repository(config, Item, logger)
    assert isinstance(repo, MongoDBRepository)


def test_duckdb_returns_duckdb_repository(logger, tmp_path):
    pytest.importorskip("duckdb")
    from arclith.adapters.outbound.duckdb.repository import DuckDBRepository
    config = AppConfig(adapters = AdaptersSettings(
        repository = "duckdb",
        duckdb = DuckDBSettings(path = str(tmp_path) + "/"),
    ))
    repo = build_repository(config, Item, logger)
    assert isinstance(repo, DuckDBRepository)
