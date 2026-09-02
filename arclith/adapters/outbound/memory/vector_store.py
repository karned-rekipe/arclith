from __future__ import annotations

import math
from collections.abc import Sequence

from arclith.domain.ports.outbound.vector_store import (
    VectorPoint,
    VectorSearchHit,
    VectorSearchQuery,
    VectorStoreCollectionNotFound,
    VectorStoreDimensionMismatch,
    VectorStorePort,
)
from arclith.infrastructure.settings.vector_store import VectorStoreSettings


class MemoryVectorStore(VectorStorePort):
    """Deterministic exact-search vector store for tests and local POCs."""

    def __init__(self, settings: VectorStoreSettings) -> None:
        self._settings = settings
        self._collections: dict[str, dict[str, VectorPoint]] = {}

    async def ensure_collection(self) -> None:
        self._collections.setdefault(self._settings.collection_name, {})

    async def upsert(self, points: Sequence[VectorPoint]) -> None:
        collection = self._collection()
        materialized = tuple(points)
        for point in materialized:
            self._validate_dimension(point.vector)
        for point in materialized:
            collection[point.id] = point.model_copy(deep=True)

    async def delete(self, ids: Sequence[str]) -> None:
        collection = self._collection()
        for point_id in ids:
            collection.pop(point_id, None)

    async def search(self, query: VectorSearchQuery) -> list[VectorSearchHit]:
        collection = self._collection()
        self._validate_dimension(query.vector)
        scored = [
            (self._score(query.vector, point.vector), point)
            for point in collection.values()
            if self._matches_filters(point, query)
        ]
        scored.sort(key=lambda item: (-item[0], item[1].id))
        return [
            VectorSearchHit(
                id=point.id,
                score=score,
                payload=point.payload if query.include_payload else {},
                vector=point.vector if query.include_vector else None,
            ).model_copy(deep=True)
            for score, point in scored
            if query.score_threshold is None or score >= query.score_threshold
        ][: query.limit]

    def _collection(self) -> dict[str, VectorPoint]:
        try:
            return self._collections[self._settings.collection_name]
        except KeyError as exc:
            raise VectorStoreCollectionNotFound(
                f"vector collection '{self._settings.collection_name}' does not exist"
            ) from exc

    def _validate_dimension(self, vector: Sequence[float]) -> None:
        actual = len(vector)
        expected = self._settings.vector_size
        if actual != expected:
            raise VectorStoreDimensionMismatch(
                f"vector dimension {actual} does not match configured size {expected}"
            )

    def _score(self, query: Sequence[float], point: Sequence[float]) -> float:
        return {
            "cosine": self._cosine,
            "dot": self._dot,
            "euclid": self._euclid_similarity,
        }[self._settings.distance](query, point)

    @staticmethod
    def _matches_filters(point: VectorPoint, query: VectorSearchQuery) -> bool:
        return all(
            key in point.payload and point.payload[key] == value
            for key, value in query.filters.items()
        )

    @staticmethod
    def _dot(left: Sequence[float], right: Sequence[float]) -> float:
        return sum(a * b for a, b in zip(left, right, strict=True))

    @classmethod
    def _cosine(cls, left: Sequence[float], right: Sequence[float]) -> float:
        denominator = math.sqrt(cls._dot(left, left) * cls._dot(right, right))
        if denominator == 0:
            return 0.0
        return cls._dot(left, right) / denominator

    @classmethod
    def _euclid_similarity(cls, left: Sequence[float], right: Sequence[float]) -> float:
        distance = math.sqrt(
            sum((a - b) ** 2 for a, b in zip(left, right, strict=True))
        )
        return 1.0 / (1.0 + distance)
