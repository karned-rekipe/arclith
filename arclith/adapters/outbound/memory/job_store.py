"""Non-durable, single-event-loop reference store for development and tests."""

import asyncio
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

from arclith.domain.errors.job import (
    JobIdempotencyConflict,
    JobNotFound,
    JobVersionConflict,
)
from arclith.domain.models.job import JobId, JobRecord, JobRequest, JobResult
from arclith.domain.ports.outbound.job_store import JobStorePort
from arclith.domain.services.job_lifecycle import JobChange, SucceedJob, transition_job
from arclith.domain.services.job_payload import payload_json, snapshot_payload


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InMemoryJobStore[RequestT: BaseModel, ResultT: BaseModel](
    JobStorePort[RequestT, ResultT]
):
    def __init__(
        self,
        request_type: type[RequestT],
        result_type: type[ResultT],
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._request_type = request_type
        self._result_type = result_type
        self._clock = clock
        self._lock = asyncio.Lock()
        self._records: dict[JobId, JobRecord[RequestT, ResultT]] = {}
        self._keys: dict[str, tuple[str, JobId]] = {}

    async def submit(
        self, request: JobRequest[RequestT]
    ) -> JobRecord[RequestT, ResultT]:
        snapshot = JobRequest[RequestT].model_validate(
            {
                **{name: getattr(request, name) for name in JobRequest.model_fields},
                "payload": snapshot_payload(request.payload, self._request_type),
            }
        )
        fingerprint = hashlib.sha256(payload_json(snapshot).encode("utf-8")).hexdigest()
        async with self._lock:
            key = snapshot.idempotency_key
            if key is not None and key in self._keys:
                previous_fingerprint, job_id = self._keys[key]
                if fingerprint != previous_fingerprint:
                    raise JobIdempotencyConflict(
                        "Idempotency key belongs to a different job request"
                    )
                return self._records[job_id].model_copy(deep=True)
            now = self._clock()
            record = JobRecord[RequestT, ResultT](
                request=snapshot, created_at=now, updated_at=now
            )
            self._records[record.job_id] = record
            if key is not None:
                self._keys[key] = (fingerprint, record.job_id)
            return record.model_copy(deep=True)

    async def get(self, job_id: JobId) -> JobRecord[RequestT, ResultT] | None:
        async with self._lock:
            record = self._records.get(job_id)
            return record.model_copy(deep=True) if record is not None else None

    async def change(
        self,
        job_id: JobId,
        change: JobChange[ResultT],
        *,
        expected_version: int,
    ) -> JobRecord[RequestT, ResultT]:
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("expected_version must be a positive integer")
        async with self._lock:
            record = self._records.get(job_id)
            if record is None:
                raise JobNotFound("Job not found")
            if record.version != expected_version:
                raise JobVersionConflict("Job version changed")
            if isinstance(change, SucceedJob):
                change = SucceedJob(
                    JobResult[ResultT](
                        schema_version=change.result.schema_version,
                        payload=snapshot_payload(
                            change.result.payload, self._result_type
                        ),
                    )
                )
            updated = transition_job(record, change, now=self._clock())
            self._records[job_id] = updated.model_copy(deep=True)
            return updated.model_copy(deep=True)

    async def purge_expired(self) -> int:
        """Explicitly remove expired terminal records AND their submission keys.

        Retention starts at the final attempt's completion. There is no timer.
        A purged key can create a new job; active jobs are never purged.
        """
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("Job clock must be timezone-aware")
        async with self._lock:
            expired = {
                job_id
                for job_id, record in self._records.items()
                if record.finished_at is not None
                and now
                >= record.finished_at + timedelta(days=record.request.retention_days)
            }
            for job_id in expired:
                del self._records[job_id]
            self._keys = {
                key: entry
                for key, entry in self._keys.items()
                if entry[1] not in expired
            }
            return len(expired)
