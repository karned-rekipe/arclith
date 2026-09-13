import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ConfigDict, Field

from arclith.adapters.outbound.memory.append_only_store import (
    InMemoryAppendOnlyStore,
)
from arclith.domain.models.immutable_record import ImmutableRecord
from arclith.domain.ports.outbound.append_only_store import (
    AppendOnlyError,
    AppendStatus,
    IdempotencyConflict,
    InvalidIdempotencyKey,
    RecordIdentityConflict,
)


class Measurement(ImmutableRecord):
    value: float
    metadata: dict[str, str] = Field(default_factory=dict)


def _measurement(
    *,
    value: float = 12.5,
    metadata: dict[str, str] | None = None,
) -> Measurement:
    return Measurement(
        occurred_at=datetime(2026, 9, 13, 12, 30, tzinfo=UTC),
        value=value,
        metadata=metadata or {},
    )


@pytest.mark.asyncio
async def test_first_append_records_the_fact_and_duplicate_returns_the_existing_fact() -> (
    None
):
    store = InMemoryAppendOnlyStore[Measurement]()
    record = _measurement()

    first = await store.append(record, idempotency_key="measurement-001")
    duplicate = await store.append(record, idempotency_key="measurement-001")

    assert first.status is AppendStatus.APPENDED
    assert duplicate.status is AppendStatus.DUPLICATE
    assert first.record.uuid == record.uuid
    assert first.record.recorded_at is not None
    assert first.record.recorded_at.tzinfo is UTC
    assert duplicate.record == first.record
    assert store.inspect_records() == (first.record,)


@pytest.mark.asyncio
async def test_recorded_at_is_excluded_from_the_idempotency_fingerprint() -> None:
    store = InMemoryAppendOnlyStore[Measurement]()
    record = _measurement()
    replay = record.model_copy(
        update={
            "recorded_at": datetime(2026, 9, 13, 12, 30, tzinfo=UTC)
            + timedelta(hours=1)
        }
    )

    await store.append(record, idempotency_key="measurement-001")
    duplicate = await store.append(replay, idempotency_key="measurement-001")

    assert duplicate.status is AppendStatus.DUPLICATE


@pytest.mark.asyncio
async def test_canonical_fingerprint_does_not_depend_on_mapping_key_order() -> None:
    store = InMemoryAppendOnlyStore[Measurement]()
    record = _measurement(metadata={"sensor": "A", "unit": "C"})
    replay = record.model_copy(update={"metadata": {"unit": "C", "sensor": "A"}})

    await store.append(record, idempotency_key="measurement-001")
    duplicate = await store.append(replay, idempotency_key="measurement-001")

    assert duplicate.status is AppendStatus.DUPLICATE


@pytest.mark.asyncio
async def test_reusing_a_key_for_different_content_raises_a_bounded_conflict() -> None:
    store = InMemoryAppendOnlyStore[Measurement]()
    secret = "patient-secret-value"
    record = _measurement(metadata={"secret": secret})

    await store.append(record, idempotency_key="private-key")

    with pytest.raises(IdempotencyConflict) as raised:
        await store.append(
            record.model_copy(update={"value": 99.0}),
            idempotency_key="private-key",
        )

    assert secret not in str(raised.value)
    assert "private-key" not in str(raised.value)


@pytest.mark.asyncio
async def test_concurrent_replays_create_exactly_one_fact() -> None:
    store = InMemoryAppendOnlyStore[Measurement]()
    record = _measurement()

    results = await asyncio.gather(
        *(store.append(record, idempotency_key="measurement-001") for _ in range(20))
    )

    assert sum(result.status is AppendStatus.APPENDED for result in results) == 1
    assert sum(result.status is AppendStatus.DUPLICATE for result in results) == 19
    assert len(store.inspect_records()) == 1


@pytest.mark.asyncio
async def test_inspection_order_is_deterministic_and_copies_are_isolated() -> None:
    store = InMemoryAppendOnlyStore[Measurement]()
    first = await store.append(_measurement(value=1.0), idempotency_key="first")
    second = await store.append(_measurement(value=2.0), idempotency_key="second")

    inspected = store.inspect_records()
    inspected[0].metadata["mutated"] = "outside"

    assert [record.uuid for record in store.inspect_records()] == [
        first.record.uuid,
        second.record.uuid,
    ]
    assert "mutated" not in store.inspect_records()[0].metadata


@pytest.mark.parametrize(
    "idempotency_key",
    ["", " leading", "trailing ", "line\nbreak", "x" * 256],
)
@pytest.mark.asyncio
async def test_invalid_idempotency_keys_are_rejected(idempotency_key: str) -> None:
    store = InMemoryAppendOnlyStore[Measurement]()

    with pytest.raises(InvalidIdempotencyKey):
        await store.append(_measurement(), idempotency_key=idempotency_key)


def test_append_only_contract_has_no_mutation_or_query_operations() -> None:
    store = InMemoryAppendOnlyStore[Measurement]()

    assert not hasattr(store, "update")
    assert not hasattr(store, "delete")
    assert not hasattr(store, "find_all")
    assert issubclass(InvalidIdempotencyKey, AppendOnlyError)
    assert issubclass(IdempotencyConflict, AppendOnlyError)


@pytest.mark.asyncio
async def test_snapshot_is_isolated_from_inputs_results_and_duplicates() -> None:
    store = InMemoryAppendOnlyStore[Measurement]()
    record = _measurement(metadata={"sensor": "original"})
    first = await store.append(record, idempotency_key="one")
    record.metadata["sensor"] = "changed input"
    first.record.metadata["sensor"] = "changed output"

    with pytest.raises(IdempotencyConflict):
        await store.append(record, idempotency_key="one")
    restored = record.model_copy(update={"metadata": {"sensor": "original"}})
    duplicate = await store.append(restored, idempotency_key="one")
    duplicate.record.metadata["sensor"] = "changed duplicate"
    assert store.inspect_records()[0].metadata == {"sensor": "original"}


@pytest.mark.asyncio
async def test_clock_is_deterministic_and_only_called_on_first_append() -> None:
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    calls: list[None] = []

    def clock() -> datetime:
        calls.append(None)
        return instant

    store = InMemoryAppendOnlyStore[Measurement](clock=clock)
    record = _measurement()
    first = await store.append(record, idempotency_key="one")
    duplicate = await store.append(record, idempotency_key="one")

    assert first.record.recorded_at == instant
    assert duplicate.record == first.record
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_invalid_clock_does_not_commit_a_record() -> None:
    store = InMemoryAppendOnlyStore[Measurement](clock=lambda: datetime(2026, 1, 1))
    with pytest.raises(AppendOnlyError, match="clock must be timezone-aware"):
        await store.append(_measurement(), idempotency_key="one")
    assert store.inspect_records() == ()


@pytest.mark.asyncio
async def test_uuid_cannot_be_appended_under_another_key() -> None:
    store = InMemoryAppendOnlyStore[Measurement]()
    record = _measurement()
    await store.append(record, idempotency_key="one")
    with pytest.raises(RecordIdentityConflict):
        await store.append(record, idempotency_key="two")
    assert len(store.inspect_records()) == 1


@pytest.mark.asyncio
async def test_conflicting_concurrent_requests_do_not_overwrite_the_winner() -> None:
    store = InMemoryAppendOnlyStore[Measurement]()
    record = _measurement()
    results = await asyncio.gather(
        store.append(record, idempotency_key="one"),
        store.append(record.model_copy(update={"value": 42.0}), idempotency_key="one"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, IdempotencyConflict) for result in results) == 1
    assert len(store.inspect_records()) == 1
    assert store.inspect_records()[0].value == 12.5


@pytest.mark.asyncio
async def test_mutable_subclass_is_rejected() -> None:
    class MutableRecord(ImmutableRecord):
        model_config = ConfigDict(frozen=False)

    store = InMemoryAppendOnlyStore[MutableRecord]()
    with pytest.raises(AppendOnlyError, match="frozen ImmutableRecord"):
        await store.append(
            MutableRecord(occurred_at=datetime(2026, 1, 1, tzinfo=UTC)),
            idempotency_key="one",
        )
