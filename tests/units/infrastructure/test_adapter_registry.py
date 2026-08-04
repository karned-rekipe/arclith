import pytest

from arclith.infrastructure.adapter_registry import AdapterRegistry
from arclith.infrastructure.config import AppConfig
from tests.units.conftest import DummyEntity, NullLogger


def _config(repository: str) -> AppConfig:
    data: dict = {"adapters": {"repository": repository}}
    if repository == "mongodb":
        data["adapters"]["mongodb"] = {"db_name": "test"}
    elif repository == "duckdb":
        data["adapters"]["duckdb"] = {"path": "data/"}
    return AppConfig.model_validate(data)


# ── register + build ──────────────────────────────────────────────────────────

def test_register_and_build_memory():
    from arclith.adapters.outbound.memory.repository import InMemoryRepository

    registry: AdapterRegistry[DummyEntity] = (
        AdapterRegistry()
        .register("memory", lambda cfg, log: InMemoryRepository())
    )
    repo = registry.build(_config("memory"), NullLogger())
    assert isinstance(repo, InMemoryRepository)


def test_fluent_chaining_returns_registry():
    registry: AdapterRegistry[DummyEntity] = AdapterRegistry()
    result = registry.register("memory", lambda cfg, log: None)  # type: ignore[arg-type]
    assert result is registry


def test_register_overwrites_previous():
    sentinel_a = object()
    sentinel_b = object()
    registry: AdapterRegistry[DummyEntity] = (
        AdapterRegistry()
        .register("memory", lambda cfg, log: sentinel_a)  # type: ignore[arg-type]
        .register("memory", lambda cfg, log: sentinel_b)  # type: ignore[arg-type]
    )
    result = registry.build(_config("memory"), NullLogger())
    assert result is sentinel_b


# ── error on unknown adapter ──────────────────────────────────────────────────

def test_build_unknown_adapter_raises_value_error():
    registry: AdapterRegistry[DummyEntity] = AdapterRegistry().register(
        "memory", lambda cfg, log: None  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="mongodb"):
        registry.build(_config("mongodb"), NullLogger())


def test_error_message_lists_available_adapters():
    registry: AdapterRegistry[DummyEntity] = (
        AdapterRegistry()
        .register("memory", lambda cfg, log: None)  # type: ignore[arg-type]
        .register("duckdb", lambda cfg, log: None)  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="Available"):
        registry.build(_config("mongodb"), NullLogger())


def test_empty_registry_raises():
    registry: AdapterRegistry[DummyEntity] = AdapterRegistry()
    with pytest.raises(ValueError):
        registry.build(_config("memory"), NullLogger())

