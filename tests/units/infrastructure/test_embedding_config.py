from pathlib import Path

import pytest
from pydantic import ValidationError

from arclith.infrastructure.config import load_config_dir


def test_load_config_dir_loads_scoped_embedding_settings(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    embedding_dir = config_dir / "adapters" / "outbound"
    embedding_dir.mkdir(parents=True)
    (embedding_dir / "embedding.yaml").write_text(
        "adapter: deterministic\n"
        "model_name: deterministic-local\n"
        "dimensions: 32\n"
        "batch_size: 8\n"
        "normalize: false\n"
        "multitenant: false\n",
        encoding="utf-8",
    )

    config = load_config_dir(config_dir)

    assert config.adapters.embedding is not None
    assert config.adapters.embedding.model_name == "deterministic-local"
    assert config.adapters.embedding.dimensions == 32
    assert config.adapters.embedding.batch_size == 8
    assert config.adapters.embedding.normalize is False


@pytest.mark.parametrize("field", ["dimensions", "batch_size"])
def test_embedding_settings_require_positive_sizes(tmp_path: Path, field: str) -> None:
    config_dir = tmp_path / "config"
    embedding_dir = config_dir / "adapters" / "outbound"
    embedding_dir.mkdir(parents=True)
    values = {"dimensions": 12, "batch_size": 4}
    values[field] = 0
    (embedding_dir / "embedding.yaml").write_text(
        "adapter: deterministic\n"
        "model_name: deterministic-local\n"
        f"dimensions: {values['dimensions']}\n"
        f"batch_size: {values['batch_size']}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match=field):
        load_config_dir(config_dir)
