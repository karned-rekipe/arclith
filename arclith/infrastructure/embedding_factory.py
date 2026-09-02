from __future__ import annotations

from collections.abc import Callable

from arclith.domain.ports.outbound.embedding import EmbeddingPort
from arclith.domain.ports.outbound.logger import Logger
from arclith.infrastructure.config import AppConfig

EmbeddingFactory = Callable[[AppConfig, Logger], EmbeddingPort]


class EmbeddingRegistry:
    """Registry mapping embedding adapter names to factories."""

    def __init__(self) -> None:
        self._factories: dict[str, EmbeddingFactory] = {}

    def register(self, name: str, factory: EmbeddingFactory) -> "EmbeddingRegistry":
        self._factories[name] = factory
        return self

    def build(self, config: AppConfig, logger: Logger) -> EmbeddingPort:
        settings = config.adapters.embedding
        if settings is None:
            raise ValueError("adapters.embedding is required to build embeddings")
        if settings.adapter not in self._factories:
            raise ValueError(
                f"Embedding adapter '{settings.adapter}' not registered. "
                f"Available: {sorted(self._factories)}."
            )
        return self._factories[settings.adapter](config, logger)


def build_embedding(
    config: AppConfig,
    logger: Logger,
    *,
    registry: EmbeddingRegistry | None = None,
) -> EmbeddingPort:
    active_registry = registry or default_embedding_registry()
    return active_registry.build(config, logger)


def default_embedding_registry() -> EmbeddingRegistry:
    return EmbeddingRegistry().register("deterministic", _build_deterministic)


def _build_deterministic(config: AppConfig, _logger: Logger) -> EmbeddingPort:
    from arclith.adapters.outbound.deterministic import (
        DeterministicEmbeddingAdapter,
    )

    settings = config.adapters.embedding
    if settings is None:
        raise ValueError("Deterministic embedding settings are required")
    return DeterministicEmbeddingAdapter(settings)
