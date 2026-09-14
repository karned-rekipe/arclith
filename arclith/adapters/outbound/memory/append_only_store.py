import asyncio
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Generic, TypeVar
from uuid import UUID

from arclith.domain.models.immutable_record import ImmutableRecord
from arclith.domain.ports.outbound.append_only_store import (
    AppendOnlyError,
    AppendOnlyStore,
    AppendResult,
    AppendStatus,
    IdempotencyConflict,
    InvalidIdempotencyKey,
    RecordIdentityConflict,
)
from arclith.domain.services.append_only import record_fingerprint

RecordT = TypeVar("RecordT", bound=ImmutableRecord)
_MAX_IDEMPOTENCY_KEY_LENGTH = 255


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class _StoredAppend(Generic[RecordT]):
    fingerprint: str
    record: RecordT


class InMemoryAppendOnlyStore(AppendOnlyStore[RecordT], Generic[RecordT]):
    """Deterministic, process-local append-only reference adapter.

    The adapter is safe for concurrent coroutines in one event loop. It is not
    durable and does not provide distributed coordination.
    """

    def __init__(self, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._by_key: dict[str, _StoredAppend[RecordT]] = {}
        self._records: dict[UUID, RecordT] = {}
        self._lock = asyncio.Lock()
        self._clock = clock

    async def append(
        self,
        record: RecordT,
        *,
        idempotency_key: str,
    ) -> AppendResult[RecordT]:
        _validate_idempotency_key(idempotency_key)
        _validate_record_contract(record)
        snapshot = record.model_copy(deep=True)
        fingerprint = record_fingerprint(snapshot)

        async with self._lock:
            existing = self._by_key.get(idempotency_key)
            if existing is not None:
                if existing.fingerprint != fingerprint or type(
                    existing.record
                ) is not type(snapshot):
                    raise IdempotencyConflict(
                        "Idempotency key already belongs to different record content"
                    )
                return AppendResult(
                    status=AppendStatus.DUPLICATE,
                    record=existing.record.model_copy(deep=True),
                )

            if snapshot.uuid in self._records:
                raise RecordIdentityConflict(
                    "Record identity already belongs to another append request"
                )
            recorded_at = self._clock()
            if recorded_at.utcoffset() is None:
                raise AppendOnlyError("Append store clock must be timezone-aware")
            stored = snapshot.model_copy(
                update={"recorded_at": recorded_at.astimezone(UTC)}
            )
            self._by_key[idempotency_key] = _StoredAppend(
                fingerprint=fingerprint,
                record=stored,
            )
            self._records[stored.uuid] = stored
            return AppendResult(
                status=AppendStatus.APPENDED,
                record=stored.model_copy(deep=True),
            )

    def inspect_records(self) -> tuple[RecordT, ...]:
        """Return isolated copies in append order for tests and diagnostics."""

        return tuple(record.model_copy(deep=True) for record in self._records.values())


def _validate_idempotency_key(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > _MAX_IDEMPOTENCY_KEY_LENGTH
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise InvalidIdempotencyKey(
            "Idempotency key must be 1-255 characters without surrounding "
            "whitespace or control characters"
        )


def _validate_record_contract(record: ImmutableRecord) -> None:
    """Guard inherited technical fields even when callers bypass Pydantic validation."""
    if not isinstance(record, ImmutableRecord) or not record.model_config.get("frozen"):
        raise AppendOnlyError("Append requires a frozen ImmutableRecord")
    for record_type in type(record).__mro__:
        if record_type is ImmutableRecord:
            break
        if ImmutableRecord.model_fields.keys() & record_type.__dict__.get(
            "__annotations__", {}
        ):
            raise AppendOnlyError("Record technical fields must remain inherited")
    if (
        not isinstance(record.uuid, UUID)
        or not _is_aware_datetime(record.occurred_at)
        or (
            record.recorded_at is not None
            and not _is_aware_datetime(record.recorded_at)
        )
    ):
        raise AppendOnlyError(
            "Record technical values must be a UUID and aware datetimes"
        )


def _is_aware_datetime(value: object) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None
