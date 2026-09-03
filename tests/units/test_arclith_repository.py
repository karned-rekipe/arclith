from arclith import Arclith, Entity, Repository, RepositoryRegistry
from arclith.adapters.outbound.memory.repository import InMemoryRepository


class BoundEntity(Entity):
    pass


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
