from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from pydantic import JsonValue

from arclith.adapters.outbound.qdrant.client import (
    create_qdrant_client,
    qdrant_models,
)
from arclith.adapters.outbound.qdrant.config import (
    ResolvedQdrantConfig,
    resolve_qdrant_config,
)
from arclith.adapters.outbound.qdrant.errors import qdrant_error_from_provider
from arclith.domain.ports.outbound.vector_store import (
    VectorPoint,
    VectorSearchHit,
    VectorSearchQuery,
    VectorStoreCollectionNotFound,
    VectorStoreDimensionMismatch,
    VectorStoreError,
    VectorStoreInvalidPayload,
    VectorStorePort,
    VectorStoreUnavailable,
)
from arclith.infrastructure.settings.vector_store import VectorStoreSettings

QdrantClientFactory = Callable[[ResolvedQdrantConfig], Any]


class QdrantVectorStore(VectorStorePort):
    """Async Qdrant implementation for one configured dense-vector collection."""

    def __init__(
        self,
        settings: VectorStoreSettings,
        *,
        client: Any | None = None,
        client_factory: QdrantClientFactory = create_qdrant_client,
    ) -> None:
        self._settings = settings
        self._injected_client = client
        self._client_factory = client_factory
        self._default_client: Any | None = None

    async def ensure_collection(self) -> None:
        async with self._client_scope() as (resolved, client):
            exists = await self._call(
                client,
                "collection_exists",
                collection_name=resolved.collection_name,
            )
            if exists:
                return
            if not resolved.create_collection:
                raise VectorStoreCollectionNotFound(
                    "qdrant vector-store collection was not found"
                )
            models = qdrant_models()
            await self._call(
                client,
                "create_collection",
                collection_name=resolved.collection_name,
                vectors_config=models.VectorParams(
                    size=resolved.vector_size,
                    distance=_distance(models, resolved.distance),
                ),
            )

    async def upsert(self, points: Sequence[VectorPoint]) -> None:
        materialized = tuple(points)
        self._validate_dimensions(point.vector for point in materialized)
        if not materialized:
            return
        models = qdrant_models()
        provider_points = [
            models.PointStruct(
                id=point.id,
                vector=list(point.vector),
                payload=dict(point.payload),
            )
            for point in materialized
        ]
        async with self._client_scope() as (resolved, client):
            await self._call(
                client,
                "upsert",
                collection_name=resolved.collection_name,
                points=provider_points,
            )

    async def delete(self, ids: Sequence[str]) -> None:
        point_ids = _normalized_point_ids(ids)
        if not point_ids:
            return
        models = qdrant_models()
        async with self._client_scope() as (resolved, client):
            await self._call(
                client,
                "delete",
                collection_name=resolved.collection_name,
                points_selector=models.PointIdsList(points=point_ids),
            )

    async def search(self, query: VectorSearchQuery) -> list[VectorSearchHit]:
        self._validate_dimensions((query.vector,))
        models = qdrant_models()
        query_filter = _query_filter(models, query.filters)
        async with self._client_scope() as (resolved, client):
            response = await self._call(
                client,
                "query_points",
                collection_name=resolved.collection_name,
                query=list(query.vector),
                query_filter=query_filter,
                limit=query.limit,
                score_threshold=query.score_threshold,
                with_payload=query.include_payload,
                with_vectors=query.include_vector,
            )
        return _search_hits(response, query)

    async def close(self) -> None:
        """Close the reusable single-tenant client owned by this adapter."""

        if self._default_client is None:
            return
        client = self._default_client
        self._default_client = None
        try:
            await client.close()
        except Exception as error:
            raise qdrant_error_from_provider(error) from error

    def _validate_dimensions(self, vectors: Iterable[Sequence[float]]) -> None:
        expected = self._settings.vector_size
        for vector in vectors:
            actual = len(vector)
            if actual != expected:
                raise VectorStoreDimensionMismatch(
                    f"vector dimension {actual} does not match configured size {expected}"
                )

    @asynccontextmanager
    async def _client_scope(
        self,
    ) -> AsyncIterator[tuple[ResolvedQdrantConfig, Any]]:
        resolved = resolve_qdrant_config(self._settings)
        if self._injected_client is not None:
            yield resolved, self._injected_client
            return
        if not self._settings.multitenant:
            if self._default_client is None:
                self._default_client = self._client_factory(resolved)
            yield resolved, self._default_client
            return

        client = self._client_factory(resolved)
        try:
            yield resolved, client
        finally:
            await _close_transient_client(client)

    @staticmethod
    async def _call(client: Any, operation: str, **kwargs: Any) -> Any:
        try:
            return await getattr(client, operation)(**kwargs)
        except VectorStoreError:
            raise
        except Exception as error:
            raise qdrant_error_from_provider(error) from error


async def _close_transient_client(client: Any) -> None:
    try:
        await client.close()
    except Exception:
        # A close failure must not hide the operation result or its mapped error.
        return


def _distance(models: Any, distance: str) -> Any:
    return {
        "cosine": models.Distance.COSINE,
        "dot": models.Distance.DOT,
        "euclid": models.Distance.EUCLID,
    }[distance]


def _query_filter(models: Any, filters: Mapping[str, JsonValue]) -> Any | None:
    if not filters:
        return None
    conditions = []
    for key, value in filters.items():
        if not isinstance(value, (bool, int, str)):
            raise VectorStoreInvalidPayload(
                "qdrant exact-match filters support string, integer and boolean values"
            )
        conditions.append(
            models.FieldCondition(key=key, match=models.MatchValue(value=value))
        )
    return models.Filter(must=conditions)


def _normalized_point_ids(ids: Sequence[str]) -> list[str]:
    normalized = [point_id.strip() for point_id in ids]
    if any(not point_id for point_id in normalized):
        raise VectorStoreInvalidPayload("qdrant point IDs must not be empty")
    return normalized


def _search_hits(response: Any, query: VectorSearchQuery) -> list[VectorSearchHit]:
    points = getattr(response, "points", None)
    if not isinstance(points, list):
        raise VectorStoreUnavailable("qdrant vector-store returned an invalid response")
    try:
        return [_search_hit(point, query) for point in points]
    except VectorStoreError:
        raise
    except (AttributeError, TypeError, ValueError) as error:
        raise VectorStoreInvalidPayload(
            "qdrant vector-store returned an invalid search result"
        ) from error


def _search_hit(point: Any, query: VectorSearchQuery) -> VectorSearchHit:
    raw_payload = getattr(point, "payload", None)
    if query.include_payload and raw_payload is not None:
        if not isinstance(raw_payload, dict):
            raise VectorStoreInvalidPayload(
                "qdrant vector-store returned an invalid payload"
            )
        payload = raw_payload
    else:
        payload = {}
    point_id = getattr(point, "id", None)
    if isinstance(point_id, bool) or not isinstance(point_id, (int, str, UUID)):
        raise VectorStoreInvalidPayload(
            "qdrant vector-store returned an invalid point ID"
        )
    return VectorSearchHit(
        id=str(point_id),
        score=float(getattr(point, "score")),
        payload=payload,
        vector=_response_vector(point, query.include_vector),
    )


def _response_vector(point: Any, include_vector: bool) -> list[float] | None:
    if not include_vector:
        return None
    vector = getattr(point, "vector", None)
    if not isinstance(vector, list) or any(
        isinstance(component, (list, dict)) for component in vector
    ):
        raise VectorStoreInvalidPayload(
            "qdrant vector-store returned a non-dense vector"
        )
    return [float(component) for component in vector]
