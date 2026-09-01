from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arclith.adapters.inbound.langgraph_runtime import server
from arclith.adapters.inbound.langgraph_runtime.catalog import InMemoryRuntimeCatalog
from arclith.adapters.outbound.noop.observability import NoOpObservabilityRuntime
from arclith.infrastructure.langgraph_bootstrap import (
    LANGGRAPH_OBSERVABILITY_RUNTIME_ATTR,
)


class FakePool:
    def __init__(self) -> None:
        self.opened = False
        self.closed = False

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True


class FakeRedis:
    def __init__(self, *, healthy: bool = True) -> None:
        self.healthy = healthy
        self.closed = False

    async def ping(self) -> bool:
        return self.healthy

    async def aclose(self) -> None:
        self.closed = True


class FakeGraph:
    checkpointer: Any = None
    store: Any = None

    async def ainvoke(self, value: Any, config: Any) -> Any:
        return value

    async def astream(self, value: Any, config: Any, **kwargs: Any) -> Any:
        if False:
            yield value


class FakePersistence:
    def __init__(self) -> None:
        self.setup_called = False

    async def setup(self) -> None:
        self.setup_called = True


class RecordingObservability(NoOpObservabilityRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[str] = []

    def start(self) -> None:
        self.events.append("start")

    def instrument_fastapi(self, app: Any) -> None:
        self.events.append("instrument_fastapi")

    def force_flush(self, timeout: float | None = None) -> bool:
        self.events.append("force_flush")
        return True

    def shutdown(self, timeout: float | None = None) -> None:
        self.events.append("shutdown")


@pytest.mark.asyncio
async def test_build_persistence_sets_up_saver_and_store(monkeypatch: Any) -> None:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.store.postgres.aio import AsyncPostgresStore

    saver = FakePersistence()
    store = FakePersistence()

    monkeypatch.setattr(
        server,
        "AsyncPostgresSaver",
        AsyncPostgresSaver,
        raising=False,
    )
    monkeypatch.setattr(AsyncPostgresSaver, "__new__", lambda _cls, _pool: saver)
    monkeypatch.setattr(AsyncPostgresStore, "__new__", lambda _cls, _pool: store)

    resolved = await server._build_langgraph_persistence(object(), setup=True)

    assert resolved == (saver, store)
    assert saver.setup_called is True
    assert store.setup_called is True

    saver.setup_called = False
    store.setup_called = False
    assert await server._build_langgraph_persistence(object(), setup=False) == (
        saver,
        store,
    )
    assert saver.setup_called is False
    assert store.setup_called is False


def test_create_durable_app_owns_resources_and_attaches_persistence(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    pool = FakePool()
    redis = FakeRedis()
    graph = FakeGraph()
    observability = RecordingObservability()
    setattr(graph, LANGGRAPH_OBSERVABILITY_RUNTIME_ATTR, observability)
    saver = FakePersistence()
    store = FakePersistence()

    async def build_persistence(_pool: Any, *, setup: bool) -> tuple[Any, Any]:
        assert setup is True
        return saver, store

    monkeypatch.setattr(server, "load_graphs", lambda _path: {"demo": graph})
    monkeypatch.setattr(
        server,
        "_postgres_catalog",
        lambda _uri: (pool, InMemoryRuntimeCatalog()),
    )
    monkeypatch.setattr(server, "_redis_client", lambda _uri: redis)
    monkeypatch.setattr(server, "_build_langgraph_persistence", build_persistence)

    app = server.create_durable_langgraph_runtime_app(
        tmp_path / "langgraph.json",
        database_uri="postgresql://database/runtime",
        redis_uri="redis://cache/1",
        redis_prefix="demo",
        run_timeout_seconds=42,
    )
    with TestClient(app) as client:
        assert client.get("/ready").json() == {"status": "ready"}
        assert graph.checkpointer is saver
        assert graph.store is store
        assert pool.opened is True

    assert pool.closed is True
    assert redis.closed is True
    assert observability.events == [
        "instrument_fastapi",
        "start",
        "force_flush",
        "shutdown",
    ]


def test_graph_observability_runtime_requires_one_valid_shared_instance() -> None:
    first = FakeGraph()
    second = FakeGraph()
    shared = RecordingObservability()
    setattr(first, LANGGRAPH_OBSERVABILITY_RUNTIME_ATTR, shared)
    setattr(second, LANGGRAPH_OBSERVABILITY_RUNTIME_ATTR, shared)

    assert server._graph_observability_runtime([first, second]) is shared
    assert isinstance(
        server._graph_observability_runtime([FakeGraph()]),
        NoOpObservabilityRuntime,
    )

    setattr(second, LANGGRAPH_OBSERVABILITY_RUNTIME_ATTR, RecordingObservability())
    with pytest.raises(RuntimeError, match="meme instance Arclith"):
        server._graph_observability_runtime([first, second])

    setattr(second, LANGGRAPH_OBSERVABILITY_RUNTIME_ATTR, object())
    with pytest.raises(TypeError, match="invalide"):
        server._graph_observability_runtime([second])


def test_create_durable_app_rejects_unhealthy_redis(
    monkeypatch: Any,
) -> None:
    pool = FakePool()
    redis = FakeRedis(healthy=False)
    graph = FakeGraph()

    async def build_persistence(_pool: Any, *, setup: bool) -> tuple[Any, Any]:
        assert setup is True
        return FakePersistence(), FakePersistence()

    monkeypatch.setattr(server, "load_graphs", lambda _path: {"demo": graph})
    monkeypatch.setattr(
        server,
        "_postgres_catalog",
        lambda _uri: (pool, InMemoryRuntimeCatalog()),
    )
    monkeypatch.setattr(server, "_redis_client", lambda _uri: redis)
    monkeypatch.setattr(server, "_build_langgraph_persistence", build_persistence)

    app = server.create_durable_langgraph_runtime_app(
        database_uri="postgresql://database/runtime",
        redis_uri="redis://cache/1",
    )
    with pytest.raises(RuntimeError, match="Redis coordination"):
        with TestClient(app):
            pass
    assert pool.closed is True
    assert redis.closed is True


def test_server_configuration_helpers(monkeypatch: Any) -> None:
    monkeypatch.delenv("DATABASE_URI", raising=False)
    monkeypatch.delenv("POSTGRESQL_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URI"):
        server._required_uri(
            None,
            primary_env="DATABASE_URI",
            fallback_env="POSTGRESQL_URL",
        )

    monkeypatch.setenv("DATABASE_URI", "postgresql+psycopg://host/database")
    assert (
        server._required_uri(
            None,
            primary_env="DATABASE_URI",
            fallback_env="POSTGRESQL_URL",
        )
        == "postgresql://host/database"
    )
    assert (
        server._normalize_postgresql_scheme("postgresql+asyncpg://host/database")
        == "postgresql://host/database"
    )
    assert server._normalize_postgresql_scheme("redis://host/1") == "redis://host/1"

    monkeypatch.delenv("RUNTIME_TEST_NUMBER", raising=False)
    assert server._positive_int_env("RUNTIME_TEST_NUMBER", 7) == 7
    monkeypatch.setenv("RUNTIME_TEST_NUMBER", "8")
    assert server._positive_int_env("RUNTIME_TEST_NUMBER", 7) == 8
    monkeypatch.setenv("RUNTIME_TEST_NUMBER", "0")
    with pytest.raises(ValueError, match="strictement positif"):
        server._positive_int_env("RUNTIME_TEST_NUMBER", 7)

    monkeypatch.delenv("RUNTIME_TEST_BOOLEAN", raising=False)
    assert server._boolean_env("RUNTIME_TEST_BOOLEAN", True) is True
    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv("RUNTIME_TEST_BOOLEAN", value)
        assert server._boolean_env("RUNTIME_TEST_BOOLEAN", False) is True
    for value in ("0", "false", "NO", "off"):
        monkeypatch.setenv("RUNTIME_TEST_BOOLEAN", value)
        assert server._boolean_env("RUNTIME_TEST_BOOLEAN", True) is False
    monkeypatch.setenv("RUNTIME_TEST_BOOLEAN", "invalid")
    with pytest.raises(ValueError, match="booleen"):
        server._boolean_env("RUNTIME_TEST_BOOLEAN", True)


def test_server_builders_and_main(monkeypatch: Any) -> None:
    pool, catalog = server._postgres_catalog("postgresql://host/database")
    assert catalog is not None
    assert pool.closed is True

    redis = server._redis_client("redis://host/1")
    assert redis.connection_pool.connection_kwargs["db"] == 1

    graph = FakeGraph()
    saver = FakePersistence()
    store = FakePersistence()
    server._attach_persistence([graph], saver=saver, store=store)
    assert graph.checkpointer is saver
    assert graph.store is store

    app = FastAPI()
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        server,
        "create_durable_langgraph_runtime_app",
        lambda config: app,
    )

    def run(received_app: Any, **options: Any) -> None:
        captured.update({"app": received_app, **options})

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", run)
    server.main(
        [
            "--config",
            "runtime.json",
            "--host",
            "127.0.0.1",
            "--port",
            "2124",
            "--graceful-timeout",
            "45",
        ]
    )
    assert captured["app"] is app
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 2124
    assert captured["timeout_graceful_shutdown"] == 45
