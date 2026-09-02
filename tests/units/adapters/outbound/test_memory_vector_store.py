import pytest

from arclith.adapters.outbound.memory.vector_store import MemoryVectorStore
from arclith.domain.ports.outbound.vector_store import (
    VectorPoint,
    VectorSearchQuery,
    VectorStoreCollectionNotFound,
    VectorStoreDimensionMismatch,
)
from arclith.infrastructure.settings.vector_store import VectorStoreSettings


def _store(*, distance: str = "cosine") -> MemoryVectorStore:
    return MemoryVectorStore(
        VectorStoreSettings(
            adapter="memory",
            collection_name="documents",
            vector_size=2,
            distance=distance,
        )
    )


@pytest.mark.asyncio
async def test_memory_vector_store_requires_collection_initialization() -> None:
    store = _store()

    with pytest.raises(VectorStoreCollectionNotFound, match="documents"):
        await store.search(VectorSearchQuery(vector=[1.0, 0.0]))


@pytest.mark.asyncio
async def test_memory_vector_store_upserts_searches_filters_and_projects() -> None:
    store = _store()
    await store.ensure_collection()
    await store.ensure_collection()
    await store.upsert(
        [
            VectorPoint(
                id="near", vector=[1.0, 0.0], payload={"kind": "guide", "v": 1}
            ),
            VectorPoint(id="far", vector=[0.0, 1.0], payload={"kind": "guide", "v": 2}),
            VectorPoint(
                id="excluded",
                vector=[0.9, 0.1],
                payload={"kind": "internal"},
            ),
        ]
    )

    hits = await store.search(
        VectorSearchQuery(
            vector=[1.0, 0.0],
            filters={"kind": "guide"},
            include_vector=True,
        )
    )

    assert [hit.id for hit in hits] == ["near", "far"]
    assert hits[0].payload == {"kind": "guide", "v": 1}
    assert hits[0].vector == [1.0, 0.0]
    assert hits[0].score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_memory_vector_store_applies_limit_threshold_and_projection_flags() -> (
    None
):
    store = _store(distance="dot")
    await store.ensure_collection()
    await store.upsert(
        [
            VectorPoint(id="a", vector=[1.0, 0.0], payload={"copy": "safe"}),
            VectorPoint(id="b", vector=[0.5, 0.0]),
            VectorPoint(id="c", vector=[-1.0, 0.0]),
        ]
    )

    hits = await store.search(
        VectorSearchQuery(
            vector=[1.0, 0.0],
            limit=1,
            score_threshold=0.5,
            include_payload=False,
        )
    )

    assert [(hit.id, hit.score) for hit in hits] == [("a", 1.0)]
    assert hits[0].payload == {}
    assert hits[0].vector is None


@pytest.mark.asyncio
async def test_memory_vector_store_distinguishes_missing_filter_from_json_null() -> (
    None
):
    store = _store()
    await store.ensure_collection()
    await store.upsert(
        [
            VectorPoint(id="missing", vector=[1.0, 0.0]),
            VectorPoint(id="null", vector=[1.0, 0.0], payload={"category": None}),
        ]
    )

    hits = await store.search(
        VectorSearchQuery(vector=[1.0, 0.0], filters={"category": None})
    )

    assert [hit.id for hit in hits] == ["null"]


@pytest.mark.asyncio
async def test_memory_vector_store_replaces_and_deletes_points() -> None:
    store = _store()
    await store.ensure_collection()
    await store.upsert([VectorPoint(id="doc", vector=[1.0, 0.0])])
    await store.upsert([VectorPoint(id="doc", vector=[0.0, 1.0])])

    hits = await store.search(VectorSearchQuery(vector=[0.0, 1.0]))
    assert [hit.id for hit in hits] == ["doc"]
    assert hits[0].score == pytest.approx(1.0)

    await store.delete(["missing", "doc"])
    assert await store.search(VectorSearchQuery(vector=[0.0, 1.0])) == []


@pytest.mark.asyncio
async def test_memory_vector_store_dimension_validation_is_atomic() -> None:
    store = _store()
    await store.ensure_collection()

    with pytest.raises(VectorStoreDimensionMismatch, match="configured size 2"):
        await store.upsert(
            [
                VectorPoint(id="valid", vector=[1.0, 0.0]),
                VectorPoint(id="invalid", vector=[1.0]),
            ]
        )
    assert await store.search(VectorSearchQuery(vector=[1.0, 0.0])) == []

    with pytest.raises(VectorStoreDimensionMismatch, match="configured size 2"):
        await store.search(VectorSearchQuery(vector=[1.0]))


@pytest.mark.asyncio
async def test_memory_vector_store_returns_detached_results() -> None:
    store = _store()
    await store.ensure_collection()
    point = VectorPoint(id="doc", vector=[1.0, 0.0], payload={"nested": ["value"]})
    await store.upsert([point])

    point.vector[0] = 0.0
    point.payload["nested"] = ["changed"]
    first = await store.search(
        VectorSearchQuery(vector=[1.0, 0.0], include_vector=True)
    )
    first[0].vector[0] = 0.0  # type: ignore[index]
    first[0].payload["nested"] = ["changed-again"]
    second = await store.search(
        VectorSearchQuery(vector=[1.0, 0.0], include_vector=True)
    )

    assert second[0].vector == [1.0, 0.0]
    assert second[0].payload == {"nested": ["value"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("distance", "expected_order"),
    [
        ("cosine", ["exact", "close", "far"]),
        ("dot", ["exact", "close", "far"]),
        ("euclid", ["exact", "close", "far"]),
    ],
)
async def test_memory_vector_store_orders_all_supported_distances(
    distance: str, expected_order: list[str]
) -> None:
    store = _store(distance=distance)
    await store.ensure_collection()
    await store.upsert(
        [
            VectorPoint(id="far", vector=[0.0, 1.0]),
            VectorPoint(id="close", vector=[0.8, 0.2]),
            VectorPoint(id="exact", vector=[1.0, 0.0]),
        ]
    )

    hits = await store.search(VectorSearchQuery(vector=[1.0, 0.0]))

    assert [hit.id for hit in hits] == expected_order
