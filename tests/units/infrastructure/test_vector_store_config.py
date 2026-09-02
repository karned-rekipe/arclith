from pathlib import Path

import pytest
from pydantic import ValidationError

from arclith.infrastructure.config import load_config_dir
from arclith.infrastructure.settings.vector_store import VectorStoreSettings


def test_load_config_dir_loads_scoped_vector_store_settings(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    outbound = config_dir / "adapters" / "outbound"
    outbound.mkdir(parents=True)
    (outbound / "vector_store.yaml").write_text(
        "adapter: memory\n"
        "collection_name: documents\n"
        "vector_size: 3\n"
        "distance: dot\n"
        "multitenant: false\n",
        encoding="utf-8",
    )

    config = load_config_dir(config_dir)

    assert config.adapters.vector_store == VectorStoreSettings(
        adapter="memory",
        collection_name="documents",
        vector_size=3,
        distance="dot",
        multitenant=False,
    )


def test_load_config_dir_loads_qdrant_settings(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    outbound = config_dir / "adapters" / "outbound"
    outbound.mkdir(parents=True)
    (outbound / "vector_store.yaml").write_text(
        "adapter: qdrant\n"
        "url: https://qdrant.example/\n"
        "api_key: test-key\n"
        "collection_name: documents\n"
        "vector_size: 1536\n"
        "distance: cosine\n"
        "prefer_grpc: true\n"
        "timeout: 7.5\n"
        "create_collection: false\n"
        "multitenant: true\n",
        encoding="utf-8",
    )

    settings = load_config_dir(config_dir).adapters.vector_store

    assert settings is not None
    assert settings.url == "https://qdrant.example"
    assert settings.api_key == "test-key"
    assert settings.prefer_grpc is True
    assert settings.timeout == 7.5
    assert settings.create_collection is False
    assert settings.multitenant is True


def test_qdrant_settings_apply_local_url_default() -> None:
    settings = VectorStoreSettings(
        adapter="qdrant",
        collection_name="documents",
        vector_size=3,
    )

    assert settings.url == "http://localhost:6333"


@pytest.mark.parametrize(
    "values",
    [
        {"adapter": "memory", "collection_name": " ", "vector_size": 2},
        {"adapter": "memory", "collection_name": "docs", "vector_size": 0},
        {
            "adapter": "memory",
            "collection_name": "docs",
            "vector_size": 2,
            "distance": "manhattan",
        },
        {
            "adapter": "memory",
            "collection_name": "docs",
            "vector_size": 2,
            "multitenant": True,
        },
        {
            "adapter": "qdrant",
            "url": "https://user:password@qdrant.example",
            "collection_name": "docs",
            "vector_size": 2,
        },
        {
            "adapter": "qdrant",
            "url": "file:///tmp/qdrant",
            "collection_name": "docs",
            "vector_size": 2,
        },
    ],
)
def test_vector_store_settings_reject_invalid_values(values: dict) -> None:
    with pytest.raises(ValidationError):
        VectorStoreSettings.model_validate(values)
