from collections.abc import Mapping
from typing import Any

import pytest

from arclith import (
    Arclith,
    Entity,
    RelationalColumn,
    RelationalMapperRegistry,
    Repository,
    RepositoryRegistry,
)
from arclith.adapters.outbound.memory.repository import InMemoryRepository


class BoundEntity(Entity):
    pass


class BoundEntityMapper:
    entity_class = BoundEntity
    table_name = "bound_entities"
    columns = (
        RelationalColumn("uuid", "uuid", primary_key=True),
        RelationalColumn("created_at", "datetime", indexed=True),
        RelationalColumn("updated_at", "datetime"),
        RelationalColumn("deleted_at", "datetime", nullable=True, indexed=True),
        RelationalColumn("version", "integer"),
    )
    indexes = ()

    def to_record(self, entity: BoundEntity) -> Mapping[str, Any]:
        return {
            "uuid": entity.uuid,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
            "deleted_at": entity.deleted_at,
            "version": entity.version,
        }

    def from_record(self, record: Mapping[str, Any]) -> BoundEntity:
        return BoundEntity(**dict(record))


def test_arclith_repository_routes_binding_through_application_registry(tmp_path):
    entity_path = f"{BoundEntity.__module__}.{BoundEntity.__qualname__}"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "adapters:\n"
        "  repository: memory\n"
        "  repository_bindings:\n"
        f"    {entity_path}: customdb\n",
        encoding="utf-8",
    )
    expected = InMemoryRepository[BoundEntity]()
    registry = RepositoryRegistry[BoundEntity, Repository[BoundEntity]]().register(
        "customdb", lambda config, entity_class, logger: expected
    )

    repository = Arclith(config_path).repository(BoundEntity, registry=registry)

    assert repository is expected


def test_arclith_repository_wires_relational_mapper_registry(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "adapters:\n"
        "  repository: postgresql\n"
        "  postgresql:\n"
        "    database: demo\n"
        "    mapping_strategy: structured\n"
        "    auto_create_schema: false\n",
        encoding="utf-8",
    )
    mapper = BoundEntityMapper()
    mapper_registry = RelationalMapperRegistry().register(mapper)

    repository = Arclith(config_path).repository(
        BoundEntity,
        mapper_registry=mapper_registry,
    )

    assert repository._mapper is mapper
    assert repository._config.auto_create_schema is False


def test_arclith_repository_exposes_factory_registry_guidance(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "adapters:\n  repository: memory\n",
        encoding="utf-8",
    )
    registry = RepositoryRegistry[BoundEntity, Repository[BoundEntity]]().register(
        "memory", lambda config, entity_class, logger: InMemoryRepository()
    )

    with pytest.raises(
        ValueError,
        match=r"capture it in the custom factory or extend "
        r"default_repository_registry\(\)",
    ):
        Arclith(config_path).repository(
            BoundEntity,
            registry=registry,
            mapper_registry=RelationalMapperRegistry(),
        )
