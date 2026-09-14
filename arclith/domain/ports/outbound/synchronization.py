"""Durability, idempotence and exclusivity are obligations of concrete adapters."""

from abc import ABC, abstractmethod

from pydantic import BaseModel

from arclith.domain.models.job import JobId
from arclith.domain.models.synchronization import (
    SourcePage,
    SyncChange,
    SyncCheckpoint,
    SyncMapping,
    SyncMode,
    SyncOutcome,
    SyncReport,
)


class SyncSourcePort[SourceT: BaseModel](ABC):
    @abstractmethod
    async def fetch_page(
        self, *, mode: SyncMode, cursor: str | None, limit: int
    ) -> SourcePage[SourceT]:
        """Return a bounded stable page; cursors contain no credentials or secrets.

        Keys are unique within each page and across the entire full enumeration.
        Full enumeration must be exhaustive/consistent before deactivation is
        safe. A terminal incremental page supplies a checkpoint_cursor watermark.
        """


class SyncMapper[SourceT: BaseModel, TargetT: BaseModel](ABC):
    @abstractmethod
    def map(self, source: SourceT) -> SyncMapping[TargetT] | None:
        """Explicit source-owned fields, or a deliberate skip. No business defaults."""


class SyncTargetPort[TargetT: BaseModel](ABC):
    @abstractmethod
    async def apply(self, change: SyncChange[TargetT]) -> SyncOutcome:
        """Durably and idempotently apply only owned fields within sync_name scope.

        The same external key/content has no second observable effect. Preserve
        local fields; re-observed inactive records become active. Implement all
        effects atomically, including an outbox if external effects are needed.
        """

    @abstractmethod
    async def deactivate_missing(
        self, sync_name: str, seen_external_ids: frozenset[str]
    ) -> int:
        """Atomically deactivate absent records in this scope, returning a count.

        Called only after all full pages commit. The V1 set is explicitly bounded
        by max_full_items. Repeating this operation must be idempotent.
        """


class SyncCheckpointPort(ABC):
    @abstractmethod
    async def load(self, sync_name: str) -> SyncCheckpoint | None:
        """Load durable integration state, independent from JobRecord."""

    @abstractmethod
    async def claim(
        self, sync_name: str, source_version: str, owner: JobId
    ) -> SyncCheckpoint:
        """Exclusively claim a scope or raise SyncBusy/SyncVersionConflict.

        Production stores must fence concurrent workers, including writes to the
        target. No implicit lease expiration/recovery is defined by this V1.
        """

    @abstractmethod
    async def commit(
        self, checkpoint: SyncCheckpoint, *, owner: JobId, expected_version: int
    ) -> SyncCheckpoint:
        """Atomic durable CAS; reject stale owners, source versions and versions."""

    @abstractmethod
    async def release(self, sync_name: str, owner: JobId) -> None:
        """Release only this owner's claim, after target operations have ended."""

    @abstractmethod
    async def save_report(self, report: SyncReport) -> None:
        """Persist this job's latest attempt report, even after partial failure."""

    @abstractmethod
    async def get_report(self, job_id: JobId) -> SyncReport | None:
        """Report storage has its own explicit retention, separate from job TTL."""
