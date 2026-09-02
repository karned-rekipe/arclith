from __future__ import annotations

import math
from collections.abc import Sequence

from pydantic import JsonValue

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
        hits: list[VectorSearchHit] = []
        for score, point in scored:
            if query.score_threshold is not None and score < query.score_threshold:
                continue
            hits.append(
                VectorSearchHit(
                    id=point.id,
                    score=score,
                    payload=point.payload if query.include_payload else {},
                    vector=point.vector if query.include_vector else None,
                ).model_copy(deep=True)
            )
            if len(hits) == query.limit:
                break
        return hits

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
            key in point.payload and _json_values_equal(point.payload[key], value)
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


def _json_values_equal(left: JsonValue, right: JsonValue) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, list):
        return _json_lists_equal(left, right)
    if isinstance(right, list):
        return False
    if isinstance(left, dict):
        return _json_dicts_equal(left, right)
    if isinstance(right, dict):
        return False
    return left == right


def _json_lists_equal(left: list[JsonValue], right: JsonValue) -> bool:
    if not isinstance(right, list) or len(left) != len(right):
        return False
    return all(
        _json_values_equal(left_item, right_item)
        for left_item, right_item in zip(left, right, strict=True)
    )


def _json_dicts_equal(left: dict[str, JsonValue], right: JsonValue) -> bool:
    if not isinstance(right, dict) or left.keys() != right.keys():
        return False
    return all(_json_values_equal(left[key], right[key]) for key in left)
