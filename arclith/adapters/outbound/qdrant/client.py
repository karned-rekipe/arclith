from __future__ import annotations

import math
from typing import Any

from arclith.adapters.outbound.qdrant.config import ResolvedQdrantConfig
from arclith.adapters.outbound.qdrant.errors import qdrant_error_from_provider
from arclith.domain.ports.outbound.vector_store import VectorStoreUnavailable


def create_qdrant_client(config: ResolvedQdrantConfig) -> Any:
    try:
        from qdrant_client import AsyncQdrantClient
    except ImportError as error:
        raise VectorStoreUnavailable(
            "qdrant vector-store requires optional dependency arclith[qdrant]"
        ) from error

    try:
        return AsyncQdrantClient(
            url=config.url,
            api_key=config.api_key,
            prefer_grpc=config.prefer_grpc,
            timeout=math.ceil(config.timeout),
        )
    except Exception as error:
        raise qdrant_error_from_provider(error) from error


def qdrant_models() -> Any:
    try:
        from qdrant_client import models
    except ImportError as error:
        raise VectorStoreUnavailable(
            "qdrant vector-store requires optional dependency arclith[qdrant]"
        ) from error
    return models
