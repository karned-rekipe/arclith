from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import arclith.infrastructure.langgraph_persistence_factory as factory_module
from arclith.infrastructure.config import LangGraphPersistenceSettings

LangGraphPersistenceRegistry = factory_module.LangGraphPersistenceRegistry
build_langgraph_persistence = factory_module.build_langgraph_persistence
render_langgraph_namespace = factory_module.render_langgraph_namespace
resolve_langgraph_persistence_mode = factory_module.resolve_langgraph_persistence_mode


def test_builds_memory_components_without_optional_backend_dependencies() -> None:
    settings = LangGraphPersistenceSettings.model_validate(
        {
            "enabled": True,
            "mode": "embedded",
            "checkpointer": {"adapter": "memory"},
            "store": {"adapter": "memory"},
        }
    )

    components = build_langgraph_persistence(settings)

    assert components.mode == "embedded"
    assert components.checkpointer.__class__.__name__ == "InMemorySaver"
    assert components.store.__class__.__name__ == "InMemoryStore"
    components.close()


def test_agent_server_mode_does_not_build_embedded_components() -> None:
    settings = LangGraphPersistenceSettings.model_validate(
        {
            "enabled": True,
            "mode": "agent_server",
            "checkpointer": {"adapter": "sqlite"},
            "store": {"adapter": "postgresql"},
        }
    )

    components = build_langgraph_persistence(settings)

    assert components.mode == "agent_server"
    assert components.checkpointer is None
    assert components.store is None


def test_auto_mode_detects_agent_server_and_supports_explicit_override() -> None:
    settings = LangGraphPersistenceSettings(enabled=True, mode="auto")

    assert (
        resolve_langgraph_persistence_mode(
            settings, environ={"LANGSERVE_GRAPHS": '{"agent":"graph.py:agent"}'}
        )
        == "agent_server"
    )
    assert (
        resolve_langgraph_persistence_mode(
            settings, environ={"LANGSMITH_LANGGRAPH_API_VARIANT": "local_dev"}
        )
        == "agent_server"
    )
    assert (
        resolve_langgraph_persistence_mode(
            settings,
            environ={"ARCLITH_LANGGRAPH_PERSISTENCE_MODE": "embedded"},
        )
        == "embedded"
    )


def test_registry_supports_custom_backend_and_closes_its_context() -> None:
    events: list[str] = []
    resource = object()

    @contextmanager
    def custom_checkpointer(_settings):
        events.append("open")
        try:
            yield resource
        finally:
            events.append("close")

    registry = LangGraphPersistenceRegistry().register_checkpointer(
        "dynamodb", custom_checkpointer
    )
    settings = LangGraphPersistenceSettings.model_validate(
        {
            "enabled": True,
            "mode": "embedded",
            "checkpointer": {"adapter": "dynamodb"},
            "store": {"adapter": "none"},
        }
    )

    components = build_langgraph_persistence(settings, registry=registry)

    assert components.checkpointer is resource
    assert events == ["open"]
    components.close()
    assert events == ["open", "close"]


def test_missing_backend_dependency_names_the_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = factory_module.importlib.import_module

    def import_module(name: str):
        if name == "langgraph.checkpoint.sqlite":
            raise ModuleNotFoundError(name)
        return real_import(name)

    monkeypatch.setattr(factory_module.importlib, "import_module", import_module)
    settings = LangGraphPersistenceSettings.model_validate(
        {
            "enabled": True,
            "mode": "embedded",
            "checkpointer": {"adapter": "sqlite"},
            "store": {"adapter": "none"},
        }
    )

    with pytest.raises(RuntimeError, match=r"arclith\[langgraph-persistence-sqlite\]"):
        build_langgraph_persistence(settings)


def test_namespace_template_is_rendered_as_explicit_segments() -> None:
    namespace = render_langgraph_namespace(
        "{tenant_id}:{user_id}:memories",
        {"tenant_id": "tenant-a", "user_id": "user-42"},
    )

    assert namespace == ("tenant-a", "user-42", "memories")

    with pytest.raises(ValueError, match="user_id"):
        render_langgraph_namespace(
            "{tenant_id}:{user_id}:memories", {"tenant_id": "tenant-a"}
        )


def test_invalid_auto_mode_override_is_rejected() -> None:
    settings = LangGraphPersistenceSettings(enabled=True, mode="auto")

    with pytest.raises(ValueError, match="embedded ou agent_server"):
        resolve_langgraph_persistence_mode(
            settings,
            environ={"ARCLITH_LANGGRAPH_PERSISTENCE_MODE": "invalid"},
        )


def test_custom_import_factories_run_setup_and_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Resource:
        def setup(self) -> None:
            events.append("setup")

        def close(self) -> None:
            events.append("close")

    module = SimpleNamespace(
        build_checkpointer=lambda _settings: Resource(),
        build_store=lambda _settings: Resource(),
    )
    real_import = factory_module.importlib.import_module

    def import_module(name: str):
        if name == "project.persistence":
            return module
        return real_import(name)

    monkeypatch.setattr(factory_module.importlib, "import_module", import_module)
    settings = LangGraphPersistenceSettings.model_validate(
        {
            "enabled": True,
            "mode": "embedded",
            "checkpointer": {
                "adapter": "custom",
                "factory": "project.persistence:build_checkpointer",
                "setup": True,
            },
            "store": {
                "adapter": "custom",
                "factory": "project.persistence:build_store",
                "setup": True,
            },
        }
    )

    components = build_langgraph_persistence(settings)

    assert events == ["setup", "setup"]
    components.close()
    assert events == ["setup", "setup", "close", "close"]


def test_builtin_database_factories_receive_connection_and_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    class Resource:
        def setup(self) -> None:
            calls.append(("setup", "", {}))

    def resource_factory(name: str):
        @contextmanager
        def from_conn_string(uri: str, **options: object):
            calls.append((name, uri, options))
            yield Resource()

        return SimpleNamespace(from_conn_string=from_conn_string)

    modules = {
        "langgraph.checkpoint.postgres": SimpleNamespace(
            PostgresSaver=resource_factory("postgres-checkpointer")
        ),
        "langgraph.store.postgres": SimpleNamespace(
            PostgresStore=resource_factory("postgres-store")
        ),
        "langgraph.checkpoint.mongodb": SimpleNamespace(
            MongoDBSaver=resource_factory("mongodb-checkpointer")
        ),
        "langgraph.store.mongodb": SimpleNamespace(
            MongoDBStore=resource_factory("mongodb-store"),
            create_vector_index_config=lambda **options: {"vector": options},
        ),
        "langgraph.store.redis": SimpleNamespace(
            RedisStore=resource_factory("redis-store")
        ),
    }
    real_import = factory_module.importlib.import_module

    def import_module(name: str):
        return modules.get(name) or real_import(name)

    monkeypatch.setattr(factory_module.importlib, "import_module", import_module)
    monkeypatch.setenv("POSTGRESQL_URL", "postgresql://runtime")
    monkeypatch.setenv("MONGODB_URI", "mongodb://runtime")
    monkeypatch.setenv("REDIS_URL", "redis://runtime")

    postgres = LangGraphPersistenceSettings.model_validate(
        {
            "enabled": True,
            "mode": "embedded",
            "checkpointer": {"adapter": "postgresql", "setup": True},
            "store": {"adapter": "postgresql", "setup": True},
        }
    )
    build_langgraph_persistence(postgres).close()
    mongodb = LangGraphPersistenceSettings.model_validate(
        {
            "enabled": True,
            "mode": "embedded",
            "checkpointer": {
                "adapter": "mongodb",
                "database": "agents",
                "ttl_seconds": 60,
            },
            "store": {
                "adapter": "mongodb",
                "database": "agents",
                "collection": "memory",
                "semantic_search": {
                    "enabled": True,
                    "embed": "openai:text-embedding-3-small",
                    "dims": 1536,
                },
            },
        }
    )
    build_langgraph_persistence(mongodb).close()
    redis = LangGraphPersistenceSettings.model_validate(
        {
            "enabled": True,
            "mode": "embedded",
            "checkpointer": {"adapter": "none"},
            "store": {"adapter": "redis"},
        }
    )
    build_langgraph_persistence(redis).close()

    assert ("postgres-checkpointer", "postgresql://runtime", {}) in calls
    assert ("postgres-store", "postgresql://runtime", {}) in calls
    assert (
        "mongodb-checkpointer",
        "mongodb://runtime",
        {"db_name": "agents", "ttl": 60},
    ) in calls
    mongodb_store = next(call for call in calls if call[0] == "mongodb-store")
    assert mongodb_store[1] == "mongodb://runtime"
    assert mongodb_store[2]["db_name"] == "agents"
    assert mongodb_store[2]["collection_name"] == "memory"
    assert "index_config" in mongodb_store[2]
    assert ("redis-store", "redis://runtime", {}) in calls


@pytest.mark.parametrize("adapter", ["memory", "sqlite", "postgresql"])
def test_rejects_ttl_for_backends_without_embedded_ttl_support(
    adapter: str,
) -> None:
    settings = LangGraphPersistenceSettings.model_validate(
        {
            "enabled": True,
            "mode": "embedded",
            "checkpointer": {"adapter": adapter, "ttl_seconds": 60},
            "store": {"adapter": "none"},
        }
    )

    with pytest.raises(ValueError, match="ttl_seconds n'est pas supporte"):
        build_langgraph_persistence(settings)
