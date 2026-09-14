from abc import ABC, abstractmethod

from pydantic import BaseModel

from arclith.domain.errors.job import JobCancellationRequested
from arclith.domain.models.job import JobId, JobProgress, JobRecord, JobRequest


class CancellationToken(ABC):
    @abstractmethod
    async def is_requested(self) -> bool:
        """Inspect the cancellation request for this attempt."""

    async def checkpoint(self) -> None:
        if await self.is_requested():
            raise JobCancellationRequested("Job cancellation acknowledged")


class JobContext(ABC):
    @property
    @abstractmethod
    def cancellation(self) -> CancellationToken:
        """Cooperative token; handlers checkpoint at safe interruption points."""

    @abstractmethod
    async def report_progress(self, progress: JobProgress) -> None:
        """Report a bounded percentage for the current attempt."""


class JobHandler[RequestT: BaseModel, ResultT: BaseModel](ABC):
    @abstractmethod
    async def execute(self, request: RequestT, context: JobContext) -> ResultT:
        """Implement business work explicitly and return a typed, small result."""


class JobRunnerPort[RequestT: BaseModel, ResultT: BaseModel](ABC):
    @abstractmethod
    async def submit(self, request: JobRequest[RequestT]) -> JobId:
        """Submit work; execution scheduling belongs to the selected adapter."""

    @abstractmethod
    async def cancel(self, job_id: JobId) -> JobRecord[RequestT, ResultT]:
        """Cancel queued work immediately, or request cooperative cancellation."""

    @abstractmethod
    async def retry(self, job_id: JobId) -> JobRecord[RequestT, ResultT]:
        """Explicitly requeue a failed job within its attempt budget."""
