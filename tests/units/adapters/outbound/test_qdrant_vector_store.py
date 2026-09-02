import builtins
from types import SimpleNamespace
from typing import Any

import pytest
from qdrant_client import models

from arclith.adapters.context import set_tenant_context
from arclith.adapters.outbound.qdrant import QdrantVectorStore
from arclith.adapters.outbound.qdrant.client import create_qdrant_client
from arclith.adapters.outbound.qdrant.config import (
    ResolvedQdrantConfig,
    resolve_qdrant_config,
)
from arclith.domain.models.tenant import AdapterTenantCoords, TenantContext
from arclith.domain.ports.outbound.vector_store import (
    VectorPoint,
    VectorSearchQuery,
    VectorStoreCollectionNotFound,
    VectorStoreDimensionMismatch,
    VectorStoreInvalidPayload,
    VectorStorePermissionDenied,
    VectorStoreUnavailable,
)
from arclith.infrastructure.settings.vector_store import VectorStoreSettings


class FakeProviderError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class FakeQdrantClient:
    def __init__(
        self,
        *,
        collection_exists: bool = True,
        response: Any | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.exists = collection_exists
        self.response = response or SimpleNamespace(points=[])
        self.errors = errors or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.close_count = 0

    async def collection_exists(self, **kwargs: Any) -> bool:
        return self._record("collection_exists", kwargs, self.exists)

    async def create_collection(self, **kwargs: Any) -> bool:
        return self._record("create_collection", kwargs, True)

    async def upsert(self, **kwargs: Any) -> object:
        return self._record("upsert", kwargs, object())

    async def delete(self, **kwargs: Any) -> object:
        return self._record("delete", kwargs, object())

    async def query_points(self, **kwargs: Any) -> Any:
        return self._record("query_points", kwargs, self.response)

    async def close(self) -> None:
        self.close_count += 1

    def _record(self, operation: str, kwargs: dict[str, Any], result: Any) -> Any:
        self.calls.append((operation, kwargs))
        error = self.errors.get(operation)
        if error is not None:
            raise error
        return result


def _settings(**updates: object) -> VectorStoreSettings:
    values: dict[str, object] = {
        "adapter": "qdrant",
        "url": "http://localhost:6333",
        "api_key": None,
        "collection_name": "documents",
        "vector_size": 3,
        "distance": "cosine",
        "prefer_grpc": False,
        "timeout": 5.0,
        "create_collection": True,
        "multitenant": False,
    }
    values.update(updates)
    return VectorStoreSettings.model_validate(values)


@pytest.mark.asyncio
async def test_ensure_collection_creates_missing_collection() -> None:
    client = FakeQdrantClient(collection_exists=False)
    store = QdrantVectorStore(_settings(), client=client)

    await store.ensure_collection()

    assert [operation for operation, _ in client.calls] == [
        "collection_exists",
        "create_collection",
    ]
    request = client.calls[1][1]
    assert request["collection_name"] == "documents"
    assert request["vectors_config"].size == 3
    assert request["vectors_config"].distance is models.Distance.COSINE


@pytest.mark.asyncio
async def test_ensure_collection_can_refuse_implicit_creation() -> None:
    client = FakeQdrantClient(collection_exists=False)
    store = QdrantVectorStore(
        _settings(create_collection=False),
        client=client,
    )

    with pytest.raises(VectorStoreCollectionNotFound):
        await store.ensure_collection()

    assert [operation for operation, _ in client.calls] == ["collection_exists"]


@pytest.mark.asyncio
async def test_upsert_and_delete_map_provider_models() -> None:
    client = FakeQdrantClient()
    store = QdrantVectorStore(_settings(), client=client)

    await store.upsert(
        [
            VectorPoint(
                id="8c7ecb96-2c97-4df9-bbf1-c3bd98bdfd07",
                vector=[1.0, 0.0, 0.0],
                payload={"kind": "guide", "published": True},
            )
        ]
    )
    await store.delete(["8c7ecb96-2c97-4df9-bbf1-c3bd98bdfd07"])

    upsert = client.calls[0][1]
    provider_point = upsert["points"][0]
    assert upsert["collection_name"] == "documents"
    assert provider_point.id == "8c7ecb96-2c97-4df9-bbf1-c3bd98bdfd07"
    assert provider_point.vector == [1.0, 0.0, 0.0]
    assert provider_point.payload == {"kind": "guide", "published": True}
    delete = client.calls[1][1]
    assert delete["points_selector"].points == ["8c7ecb96-2c97-4df9-bbf1-c3bd98bdfd07"]


@pytest.mark.asyncio
async def test_search_maps_query_filters_and_hits() -> None:
    point_id = "8c7ecb96-2c97-4df9-bbf1-c3bd98bdfd07"
    client = FakeQdrantClient(
        response=SimpleNamespace(
            points=[
                models.ScoredPoint(
                    id=point_id,
                    version=1,
                    score=0.98,
                    payload={"kind": "guide", "published": True},
                    vector=[1.0, 0.0, 0.0],
                )
            ]
        )
    )
    store = QdrantVectorStore(_settings(), client=client)
    query = VectorSearchQuery(
        vector=[1.0, 0.0, 0.0],
        filters={"kind": "guide", "published": True},
        limit=4,
        score_threshold=0.7,
        include_payload=True,
        include_vector=True,
    )

    hits = await store.search(query)

    request = client.calls[0][1]
    assert request["query"] == [1.0, 0.0, 0.0]
    assert request["limit"] == 4
    assert request["score_threshold"] == 0.7
    assert request["with_payload"] is True
    assert request["with_vectors"] is True
    assert request["query_filter"].must == [
        models.FieldCondition(key="kind", match=models.MatchValue(value="guide")),
        models.FieldCondition(key="published", match=models.MatchValue(value=True)),
    ]
    assert hits[0].id == point_id
    assert hits[0].score == 0.98
    assert hits[0].payload == {"kind": "guide", "published": True}
    assert hits[0].vector == [1.0, 0.0, 0.0]


@pytest.mark.asyncio
async def test_dimension_mismatch_fails_before_provider_call() -> None:
    client = FakeQdrantClient()
    store = QdrantVectorStore(_settings(), client=client)

    with pytest.raises(VectorStoreDimensionMismatch, match="configured size 3"):
        await store.upsert([VectorPoint(id="one", vector=[1.0, 0.0])])
    with pytest.raises(VectorStoreDimensionMismatch, match="configured size 3"):
        await store.search(VectorSearchQuery(vector=[1.0]))

    assert client.calls == []


@pytest.mark.asyncio
async def test_qdrant_rejects_filters_not_supported_by_match_value() -> None:
    client = FakeQdrantClient()
    store = QdrantVectorStore(_settings(), client=client)

    with pytest.raises(VectorStoreInvalidPayload, match="exact-match filters"):
        await store.search(
            VectorSearchQuery(
                vector=[1.0, 0.0, 0.0],
                filters={"nested": {"value": 1}},
            )
        )

    assert client.calls == []


@pytest.mark.asyncio
async def test_search_rejects_invalid_provider_results() -> None:
    client = FakeQdrantClient(
        response=SimpleNamespace(
            points=[SimpleNamespace(id=None, score=1.0, payload={}, vector=None)]
        )
    )
    store = QdrantVectorStore(_settings(), client=client)

    with pytest.raises(VectorStoreInvalidPayload, match="point ID"):
        await store.search(VectorSearchQuery(vector=[1.0, 0.0, 0.0]))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, VectorStorePermissionDenied),
        (403, VectorStorePermissionDenied),
        (404, VectorStoreCollectionNotFound),
        (503, VectorStoreUnavailable),
    ],
)
async def test_provider_errors_are_mapped_without_details(
    status_code: int,
    expected_error: type[Exception],
) -> None:
    client = FakeQdrantClient(errors={"query_points": FakeProviderError(status_code)})
    store = QdrantVectorStore(_settings(api_key="private-key"), client=client)

    with pytest.raises(expected_error) as error:
        await store.search(VectorSearchQuery(vector=[1.0, 0.0, 0.0]))

    assert "private-key" not in str(error.value)


@pytest.mark.asyncio
async def test_multitenant_overrides_coordinates_and_closes_transient_client() -> None:
    created: list[tuple[ResolvedQdrantConfig, FakeQdrantClient]] = []

    def client_factory(config: ResolvedQdrantConfig) -> FakeQdrantClient:
        client = FakeQdrantClient()
        created.append((config, client))
        return client

    token = set_tenant_context(
        TenantContext(
            adapters={
                "qdrant": AdapterTenantCoords(
                    params={
                        "url": "https://tenant.qdrant.example",
                        "api_key": "tenant-key",
                        "collection_name": "tenant-documents",
                    }
                )
            }
        )
    )
    try:
        await QdrantVectorStore(
            _settings(multitenant=True),
            client_factory=client_factory,
        ).search(VectorSearchQuery(vector=[1.0, 0.0, 0.0]))
    finally:
        token.var.reset(token)

    resolved, client = created[0]
    assert resolved.url == "https://tenant.qdrant.example"
    assert resolved.api_key == "tenant-key"
    assert resolved.collection_name == "tenant-documents"
    assert client.calls[0][1]["collection_name"] == "tenant-documents"
    assert client.close_count == 1


@pytest.mark.asyncio
async def test_single_tenant_reuses_owned_client_until_close() -> None:
    clients: list[FakeQdrantClient] = []

    def client_factory(_config: ResolvedQdrantConfig) -> FakeQdrantClient:
        client = FakeQdrantClient()
        clients.append(client)
        return client

    store = QdrantVectorStore(_settings(), client_factory=client_factory)

    await store.ensure_collection()
    await store.ensure_collection()
    await store.close()
    await store.close()

    assert len(clients) == 1
    assert clients[0].close_count == 1


def test_resolve_qdrant_config_falls_back_to_single_tenant_values() -> None:
    token = set_tenant_context(
        TenantContext(
            adapters={
                "qdrant": AdapterTenantCoords(
                    params={"collection_name": "tenant-documents"}
                )
            }
        )
    )
    try:
        resolved = resolve_qdrant_config(
            _settings(
                url="https://fallback.qdrant.example/",
                api_key="fallback-key",
                multitenant=True,
            )
        )
    finally:
        token.var.reset(token)

    assert resolved.url == "https://fallback.qdrant.example"
    assert resolved.api_key == "fallback-key"
    assert resolved.collection_name == "tenant-documents"


def test_create_qdrant_client_requires_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "qdrant_client" or name.startswith("qdrant_client."):
            raise ImportError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(VectorStoreUnavailable, match=r"arclith\[qdrant\]"):
        create_qdrant_client(resolve_qdrant_config(_settings()))


def test_create_qdrant_client_uses_effective_connection_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    expected = object()

    def fake_client(**kwargs: Any) -> object:
        captured.update(kwargs)
        return expected

    monkeypatch.setattr("qdrant_client.AsyncQdrantClient", fake_client)

    client = create_qdrant_client(
        resolve_qdrant_config(
            _settings(
                url="https://qdrant.example",
                api_key="test-key",
                prefer_grpc=True,
                timeout=5.2,
            )
        )
    )

    assert client is expected
    assert captured == {
        "url": "https://qdrant.example",
        "api_key": "test-key",
        "prefer_grpc": True,
        "timeout": 6,
    }
