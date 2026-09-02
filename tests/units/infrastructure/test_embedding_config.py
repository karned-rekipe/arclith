from pathlib import Path

import pytest
from pydantic import ValidationError

from arclith.infrastructure.config import load_config_dir
from arclith.infrastructure.settings.embedding import EmbeddingSettings


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


def test_embedding_settings_reject_empty_adapter_name(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    embedding_dir = config_dir / "adapters" / "outbound"
    embedding_dir.mkdir(parents=True)
    (embedding_dir / "embedding.yaml").write_text(
        "adapter: '   '\nmodel_name: deterministic-local\ndimensions: 12\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="adapters.embedding.adapter"):
        load_config_dir(config_dir)


def test_load_config_dir_loads_openai_compatible_settings(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    embedding_dir = config_dir / "adapters" / "outbound"
    embedding_dir.mkdir(parents=True)
    (embedding_dir / "embedding.yaml").write_text(
        "adapter: openai-compatible\n"
        "base_url: http://127.0.0.1:1234/v1/\n"
        "api_key: local-dev\n"
        "model_name: local-embedding-model\n"
        "dimensions: 768\n"
        "batch_size: 16\n"
        "timeout: 12.5\n"
        "normalize: false\n",
        encoding="utf-8",
    )

    config = load_config_dir(config_dir)

    assert config.adapters.embedding is not None
    assert config.adapters.embedding.adapter == "openai-compatible"
    assert config.adapters.embedding.base_url == "http://127.0.0.1:1234/v1"
    assert config.adapters.embedding.api_key == "local-dev"
    assert config.adapters.embedding.timeout == 12.5


@pytest.mark.parametrize(
    ("adapter", "expected"),
    [
        ("deterministic", True),
        ("openai-compatible", False),
        ("openai", False),
    ],
)
def test_embedding_settings_use_adapter_specific_normalization_defaults(
    adapter: str,
    expected: bool,
) -> None:
    values = {
        "adapter": adapter,
        "model_name": "embedding-model",
        "dimensions": 768,
    }
    if adapter == "openai-compatible":
        values["base_url"] = "http://127.0.0.1:1234/v1"
    if adapter == "openai":
        values["dimensions"] = None

    settings = EmbeddingSettings.model_validate(values)

    assert settings.normalize is expected


def test_openai_embedding_settings_apply_safe_official_defaults() -> None:
    settings = EmbeddingSettings.model_validate(
        {
            "adapter": "openai",
            "model_name": "configured-embedding-model",
        }
    )

    assert settings.base_url == "https://api.openai.com/v1"
    assert settings.dimensions is None
    assert settings.encoding_format == "float"
    assert settings.api_key is None


def test_openai_embedding_settings_reject_base64_encoding() -> None:
    with pytest.raises(ValidationError, match="encoding_format"):
        EmbeddingSettings.model_validate(
            {
                "adapter": "openai",
                "model_name": "configured-embedding-model",
                "encoding_format": "base64",
            }
        )


def test_load_openai_embedding_api_key_from_env_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    config_dir = tmp_path / "config"
    embedding_dir = config_dir / "adapters" / "outbound"
    embedding_dir.mkdir(parents=True)
    (embedding_dir / "embedding.yaml").write_text(
        "adapter: openai\n"
        "base_url: https://api.openai.com/v1\n"
        "api_key: null\n"
        "model_name: configured-embedding-model\n"
        "dimensions: null\n"
        "batch_size: 64\n"
        "timeout: 30.0\n"
        "encoding_format: float\n"
        "normalize: false\n"
        "multitenant: false\n",
        encoding="utf-8",
    )
    (config_dir / "secrets.yaml").write_text(
        "resolver: env\nmappings:\n  adapters.embedding.api_key: OPENAI_API_KEY\n",
        encoding="utf-8",
    )

    config = load_config_dir(config_dir)

    assert config.adapters.embedding is not None
    assert config.adapters.embedding.adapter == "openai"
    assert config.adapters.embedding.api_key == "test-key"
    assert config.adapters.embedding.dimensions is None


@pytest.mark.parametrize("adapter", ["deterministic", "openai-compatible"])
def test_existing_embedding_adapters_still_require_dimensions(adapter: str) -> None:
    values = {
        "adapter": adapter,
        "model_name": "embedding-model",
    }
    if adapter == "openai-compatible":
        values["base_url"] = "http://127.0.0.1:1234/v1"

    with pytest.raises(ValidationError, match="requires dimensions"):
        EmbeddingSettings.model_validate(values)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:1234",
        "ftp://embedding.local/v1",
        "http://user:password@embedding.local/v1",
        "http://embedding.local/v1?token=secret",
    ],
)
def test_openai_compatible_settings_reject_invalid_base_url(
    tmp_path: Path,
    base_url: str,
) -> None:
    config_dir = tmp_path / "config"
    embedding_dir = config_dir / "adapters" / "outbound"
    embedding_dir.mkdir(parents=True)
    (embedding_dir / "embedding.yaml").write_text(
        "adapter: openai-compatible\n"
        f"base_url: {base_url}\n"
        "model_name: local-embedding-model\n"
        "dimensions: 2\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="base_url"):
        load_config_dir(config_dir)
