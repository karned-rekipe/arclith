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
    ],
)
def test_vector_store_settings_reject_invalid_values(values: dict) -> None:
    with pytest.raises(ValidationError):
        VectorStoreSettings.model_validate(values)
