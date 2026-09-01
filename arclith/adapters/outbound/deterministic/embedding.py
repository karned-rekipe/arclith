from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from arclith.domain.ports.outbound.embedding import (
    EmbeddingPort,
    EmbeddingResponse,
    EmbeddingResult,
    EmbeddingText,
    validate_embedding_inputs,
)
from arclith.infrastructure.settings.embedding import EmbeddingSettings

_UINT32_RANGE = float(2**32)


class DeterministicEmbeddingAdapter(EmbeddingPort):
    """Dependency-free deterministic vectors for tests and local smoke runs."""

    def __init__(self, settings: EmbeddingSettings) -> None:
        self._settings = settings

    async def embed_texts(self, inputs: Sequence[EmbeddingText]) -> EmbeddingResponse:
        validated = validate_embedding_inputs(inputs)
        results: list[EmbeddingResult] = []

        for batch_start in range(0, len(validated), self._settings.batch_size):
            batch = validated[batch_start : batch_start + self._settings.batch_size]
            results.extend(self._embed_batch(batch, offset=batch_start))

        return EmbeddingResponse(
            results=results,
            model_name=self._settings.model_name,
            dimensions=self._settings.dimensions,
        )

    def _embed_batch(
        self,
        inputs: Sequence[EmbeddingText],
        *,
        offset: int,
    ) -> list[EmbeddingResult]:
        return [
            EmbeddingResult(
                id=item.id,
                index=offset + index,
                vector=self._vector_for(item.text),
                model_name=self._settings.model_name,
                dimensions=self._settings.dimensions,
            )
            for index, item in enumerate(inputs)
        ]

    def _vector_for(self, text: str) -> list[float]:
        vector: list[float] = []
        counter = 0
        seed = f"{self._settings.model_name}\0{text}".encode()

        while len(vector) < self._settings.dimensions:
            digest = hashlib.sha256(seed + counter.to_bytes(8, "big")).digest()
            for position in range(0, len(digest), 4):
                integer = int.from_bytes(digest[position : position + 4], "big")
                vector.append(((integer + 0.5) / _UINT32_RANGE) * 2.0 - 1.0)
                if len(vector) == self._settings.dimensions:
                    break
            counter += 1

        if not self._settings.normalize:
            return vector

        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector]
