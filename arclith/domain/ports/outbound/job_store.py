from abc import ABC, abstractmethod

from pydantic import BaseModel

from arclith.domain.models.job import JobId, JobRecord, JobRequest
from arclith.domain.services.job_lifecycle import JobChange


class JobStorePort[RequestT: BaseModel, ResultT: BaseModel](ABC):
    """Atomic submission and controlled, version-checked lifecycle changes.

    One store is scoped to one job definition and its request/result schemas.
    A duplicate key matches the complete request, including execution policy.
    Implementations isolate all returned snapshots from stored values.
    """

    @abstractmethod
    async def submit(
        self, request: JobRequest[RequestT]
    ) -> JobRecord[RequestT, ResultT]:
        """Create a queued job or return its idempotent predecessor atomically."""

    @abstractmethod
    async def get(self, job_id: JobId) -> JobRecord[RequestT, ResultT] | None:
        """Return an isolated snapshot, or None when absent/expired."""

    @abstractmethod
    async def change(
        self,
        job_id: JobId,
        change: JobChange[ResultT],
        *,
        expected_version: int,
    ) -> JobRecord[RequestT, ResultT]:
        """Check version and lifecycle in the same atomic storage operation."""
