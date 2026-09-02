from collections.abc import Sequence
from pathlib import Path

import pytest

from arclith import Arclith
from arclith.adapters.outbound.memory.vector_store import MemoryVectorStore
from arclith.adapters.outbound.qdrant import QdrantVectorStore
from arclith.domain.ports.outbound.vector_store import (
    VectorPoint,
    VectorSearchHit,
    VectorSearchQuery,
    VectorStorePort,
)
from arclith.infrastructure.config import AppConfig
from arclith.infrastructure.vector_store_factory import (
    VectorStoreRegistry,
    build_vector_store,
    default_vector_store_registry,
)


class StubVectorStore(VectorStorePort):
    async def ensure_collection(self) -> None:
        pass

    async def upsert(self, points: Sequence[VectorPoint]) -> None:
        pass

    async def delete(self, ids: Sequence[str]) -> None:
        pass

    async def search(self, query: VectorSearchQuery) -> list[VectorSearchHit]:
        return []


def _config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "adapters": {
                "vector_store": {
                    "adapter": "memory",
                    "collection_name": "documents",
                    "vector_size": 3,
                }
            }
        }
    )


def test_build_vector_store_returns_memory_adapter(logger) -> None:
    assert isinstance(build_vector_store(_config(), logger), MemoryVectorStore)


def test_build_vector_store_returns_qdrant_adapter(logger) -> None:
    config = AppConfig.model_validate(
        {
            "adapters": {
                "vector_store": {
                    "adapter": "qdrant",
                    "collection_name": "documents",
                    "vector_size": 3,
                }
            }
        }
    )

    assert isinstance(build_vector_store(config, logger), QdrantVectorStore)


def test_build_vector_store_requires_config(logger) -> None:
    with pytest.raises(ValueError, match="adapters.vector_store"):
        build_vector_store(AppConfig(), logger)


def test_default_vector_store_registry_rejects_unknown_adapter(logger) -> None:
    config = _config()
    assert config.adapters.vector_store is not None
    unknown = config.adapters.vector_store.model_copy(update={"adapter": "unknown"})
    config = config.model_copy(
        update={
            "adapters": config.adapters.model_copy(update={"vector_store": unknown})
        }
    )

    with pytest.raises(ValueError, match="not registered"):
        default_vector_store_registry().build(config, logger)


def test_custom_vector_store_registry_builds_registered_adapter(logger) -> None:
    expected = StubVectorStore()
    config = _config()
    assert config.adapters.vector_store is not None
    custom = config.adapters.vector_store.model_copy(update={"adapter": "custom"})
    config = config.model_copy(
        update={"adapters": config.adapters.model_copy(update={"vector_store": custom})}
    )
    registry = VectorStoreRegistry().register(
        "custom", lambda _config, _logger: expected
    )

    assert build_vector_store(config, logger, registry=registry) is expected


def test_arclith_builds_configured_vector_store(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    outbound = config_dir / "adapters" / "outbound"
    outbound.mkdir(parents=True)
    (outbound / "vector_store.yaml").write_text(
        "adapter: memory\ncollection_name: documents\nvector_size: 2\n",
        encoding="utf-8",
    )

    assert isinstance(Arclith(config_dir).vector_store(), MemoryVectorStore)
