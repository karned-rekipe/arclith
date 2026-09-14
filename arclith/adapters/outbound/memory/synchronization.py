"""Non-durable reference stores, restricted to coroutines in one asyncio loop."""

import asyncio

from pydantic import BaseModel, Field, JsonValue

from arclith.domain.errors.synchronization import SyncBusy, SyncVersionConflict
from arclith.domain.models.job import JobId
from arclith.domain.models.synchronization import (
    SyncChange,
    SyncCheckpoint,
    SyncMapping,
    SyncModel,
    SyncOutcome,
    SyncReport,
)
from arclith.domain.ports.outbound.synchronization import (
    SyncCheckpointPort,
    SyncTargetPort,
)
from arclith.domain.services.job_payload import payload_content, snapshot_payload


class MemorySyncRecord(SyncModel):
    fields: dict[str, JsonValue] = Field(default_factory=dict)
    active: bool = True


class InMemorySyncTarget[TargetT: BaseModel](SyncTargetPort[TargetT]):
    def __init__(
        self, target_type: type[TargetT], *, max_records: int = 100_000
    ) -> None:
        if type(max_records) is not int or max_records < 1:
            raise ValueError("max_records must be a positive integer")
        self._target_type = target_type
        self._max_records = max_records
        self._records: dict[tuple[str, str], MemorySyncRecord] = {}
        self._lock = asyncio.Lock()

    async def get_by_external_id(
        self, sync_name: str, external_id: str
    ) -> MemorySyncRecord | None:
        async with self._lock:
            value = self._records.get((sync_name, external_id))
            return value.model_copy(deep=True) if value is not None else None

    async def apply(self, change: SyncChange[TargetT]) -> SyncOutcome:
        mapping = SyncMapping(
            value=snapshot_payload(change.mapping.value, self._target_type),
            owned_fields=change.mapping.owned_fields,
        )
        validated = SyncChange(
            sync_name=change.sync_name, external_id=change.external_id, mapping=mapping
        )
        content = payload_content(validated.mapping.value)
        if not isinstance(content, dict):
            raise ValueError("Mapped content must be a JSON object")
        patch = {name: content[name] for name in mapping.owned_fields}
        async with self._lock:
            return self._apply((validated.sync_name, validated.external_id), patch)

    def _apply(self, key: tuple[str, str], patch: dict[str, JsonValue]) -> SyncOutcome:
        existing = self._records.get(key)
        if existing is None:
            if len(self._records) >= self._max_records:
                raise ValueError("In-memory sync target capacity reached")
            self._records[key] = MemorySyncRecord(fields=patch)
            return "created"
        merged = {**existing.fields, **patch}
        if existing.active and merged == existing.fields:
            return "unchanged"
        self._records[key] = MemorySyncRecord(fields=merged)
        return "updated"

    async def deactivate_missing(
        self, sync_name: str, seen_external_ids: frozenset[str]
    ) -> int:
        async with self._lock:
            missing = [
                key
                for key, value in self._records.items()
                if key[0] == sync_name
                and key[1] not in seen_external_ids
                and value.active
            ]
            # Prepare every replacement before changing the store; no partial sweep.
            replacements = {
                key: self._records[key].model_copy(update={"active": False}, deep=True)
                for key in missing
            }
            self._records.update(replacements)
            return len(replacements)


class InMemorySyncCheckpoint(SyncCheckpointPort):
    def __init__(self, *, max_reports: int = 1000) -> None:
        if type(max_reports) is not int or max_reports < 1:
            raise ValueError("max_reports must be a positive integer")
        self._checkpoints: dict[str, SyncCheckpoint] = {}
        self._owners: dict[str, JobId] = {}
        self._reports: dict[str, SyncReport] = {}
        self._max_reports = max_reports
        self._lock = asyncio.Lock()

    async def load(self, sync_name: str) -> SyncCheckpoint | None:
        async with self._lock:
            value = self._checkpoints.get(sync_name)
            return value.model_copy(deep=True) if value is not None else None

    async def claim(
        self, sync_name: str, source_version: str, owner: JobId
    ) -> SyncCheckpoint:
        async with self._lock:
            if sync_name in self._owners:
                raise SyncBusy("Synchronization scope is already running")
            checkpoint = self._checkpoints.get(sync_name) or SyncCheckpoint(
                sync_name=sync_name,
                source_version=source_version,
            )
            if checkpoint.source_version != source_version:
                raise SyncVersionConflict("Synchronization source version changed")
            self._checkpoints[sync_name] = checkpoint
            self._owners[sync_name] = owner
            return checkpoint.model_copy(deep=True)

    async def commit(
        self, checkpoint: SyncCheckpoint, *, owner: JobId, expected_version: int
    ) -> SyncCheckpoint:
        checkpoint = SyncCheckpoint.model_validate(checkpoint)
        async with self._lock:
            current = self._checkpoints.get(checkpoint.sync_name)
            version = current.version if current is not None else 0
            self._validate_commit(checkpoint, owner, expected_version, version, current)
            stored = checkpoint.model_copy(update={"version": version + 1}, deep=True)
            self._checkpoints[checkpoint.sync_name] = stored
            return stored.model_copy(deep=True)

    def _validate_commit(
        self,
        checkpoint: SyncCheckpoint,
        owner: JobId,
        expected_version: int,
        version: int,
        current: SyncCheckpoint | None,
    ) -> None:
        if self._owners.get(checkpoint.sync_name) != owner:
            raise SyncVersionConflict("Synchronization claim is not current")
        if (
            type(expected_version) is not int
            or expected_version != version
            or checkpoint.version != version
        ):
            raise SyncVersionConflict("Synchronization checkpoint version changed")
        if current is not None and current.source_version != checkpoint.source_version:
            raise SyncVersionConflict("Synchronization source version changed")

    async def release(self, sync_name: str, owner: JobId) -> None:
        async with self._lock:
            if self._owners.get(sync_name) == owner:
                del self._owners[sync_name]

    async def save_report(self, report: SyncReport) -> None:
        report = snapshot_payload(report, SyncReport)
        async with self._lock:
            if (
                report.job_id not in self._reports
                and len(self._reports) >= self._max_reports
            ):
                raise ValueError(
                    "Sync report capacity reached; explicitly delete old reports"
                )
            self._reports[report.job_id] = report

    async def get_report(self, job_id: JobId) -> SyncReport | None:
        async with self._lock:
            report = self._reports.get(str(job_id))
            return report.model_copy(deep=True) if report is not None else None

    async def delete_report(self, job_id: JobId) -> None:
        async with self._lock:
            if job_id in self._owners.values():
                raise SyncBusy("Cannot delete a running synchronization report")
            self._reports.pop(str(job_id), None)
