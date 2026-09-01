from collections.abc import Sequence
from pathlib import Path

import pytest

from arclith import Arclith
from arclith.adapters.outbound.deterministic import DeterministicEmbeddingAdapter
from arclith.domain.ports.outbound.embedding import (
    EmbeddingPort,
    EmbeddingResponse,
    EmbeddingText,
)
from arclith.infrastructure.config import AppConfig
from arclith.infrastructure.embedding_factory import (
    EmbeddingRegistry,
    build_embedding,
    default_embedding_registry,
)
from arclith.infrastructure.settings.embedding import EmbeddingSettings


class StubEmbedding(EmbeddingPort):
    async def embed_texts(self, inputs: Sequence[EmbeddingText]) -> EmbeddingResponse:
        raise NotImplementedError


def _config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "adapters": {
                "embedding": {
                    "adapter": "deterministic",
                    "model_name": "deterministic-test",
                    "dimensions": 12,
                    "batch_size": 4,
                    "normalize": True,
                }
            }
        }
    )


def test_build_embedding_returns_deterministic_adapter(logger) -> None:
    embedding = build_embedding(_config(), logger)

    assert isinstance(embedding, DeterministicEmbeddingAdapter)


def test_build_embedding_requires_config(logger) -> None:
    with pytest.raises(ValueError, match="adapters.embedding"):
        build_embedding(AppConfig(), logger)


def test_custom_embedding_registry_builds_registered_adapter(logger) -> None:
    expected = StubEmbedding()
    config = AppConfig()
    custom_settings = EmbeddingSettings.model_construct(
        adapter="custom",
        model_name="custom-model",
        dimensions=3,
        batch_size=1,
        normalize=False,
        multitenant=False,
    )
    config = config.model_copy(
        update={
            "adapters": config.adapters.model_copy(
                update={"embedding": custom_settings}
            )
        }
    )
    registry = EmbeddingRegistry().register("custom", lambda _config, _logger: expected)

    assert build_embedding(config, logger, registry=registry) is expected


def test_default_embedding_registry_rejects_unknown_adapter(logger) -> None:
    config = _config()
    assert config.adapters.embedding is not None
    unknown = config.adapters.embedding.model_copy(update={"adapter": "unknown"})
    config = config.model_copy(
        update={"adapters": config.adapters.model_copy(update={"embedding": unknown})}
    )

    with pytest.raises(ValueError, match="not registered"):
        default_embedding_registry().build(config, logger)


def test_arclith_builds_configured_embedding(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    embedding_dir = config_dir / "adapters" / "outbound"
    embedding_dir.mkdir(parents=True)
    (embedding_dir / "embedding.yaml").write_text(
        "adapter: deterministic\n"
        "model_name: deterministic-smoke\n"
        "dimensions: 6\n"
        "batch_size: 2\n"
        "normalize: true\n",
        encoding="utf-8",
    )

    app = Arclith(config_dir)

    assert isinstance(app.embedding(), DeterministicEmbeddingAdapter)
