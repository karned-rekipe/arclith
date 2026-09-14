from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

from arclith.domain.models.immutable_record import ImmutableRecord

RecordT = TypeVar("RecordT", bound=ImmutableRecord)


class AppendStatus(StrEnum):
    """Outcome of a successful append request."""

    APPENDED = "appended"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class AppendResult(Generic[RecordT]):
    """Stored record and the idempotent outcome of the append."""

    status: AppendStatus
    record: RecordT


class AppendOnlyError(Exception):
    """Base error for append-only operations."""


class InvalidIdempotencyKey(AppendOnlyError, ValueError):
    """Raised when an idempotency key does not satisfy the public contract."""


class IdempotencyConflict(AppendOnlyError):
    """Raised when a key is reused for different canonical content."""


class RecordIdentityConflict(AppendOnlyError):
    """Raised when a previously appended identity is submitted under another key."""


class AppendStoreUnavailable(AppendOnlyError):
    """Raised when an append store cannot accept a request."""


class AppendOnlyStore(ABC, Generic[RecordT]):
    """Outbound port for atomically appending immutable records."""

    @abstractmethod
    async def append(
        self,
        record: RecordT,
        *,
        idempotency_key: str,
    ) -> AppendResult[RecordT]:
        """Atomically append once within this store's idempotency scope.

        A matching key, record type and canonical fingerprint returns DUPLICATE
        with the initially stored record. Changed content raises
        IdempotencyConflict; an existing UUID under a new key raises
        RecordIdentityConflict. The store owns recorded_at and assigns it only
        on the first append. Returned records must not allow callers to mutate
        stored content. See domain.services.append_only for canonical content.
        """

        raise NotImplementedError  # pragma: no cover
