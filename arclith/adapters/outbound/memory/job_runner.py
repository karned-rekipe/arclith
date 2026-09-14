"""Caller-owned deterministic execution; no background tasks or implicit retries."""

import asyncio

from pydantic import BaseModel

from arclith.domain.errors.job import (
    JobCancellationRequested,
    JobNotFound,
    JobTransitionError,
    JobVersionConflict,
)
from arclith.domain.models.job import (
    JobError,
    JobId,
    JobProgress,
    JobRecord,
    JobRequest,
    JobResult,
    JobStatus,
)
from arclith.domain.ports.outbound.job_runner import (
    CancellationToken,
    JobContext,
    JobHandler,
    JobRunnerPort,
)
from arclith.domain.ports.outbound.job_store import JobStorePort
from arclith.domain.services.job_lifecycle import (
    AcknowledgeJobCancellation,
    CancelJob,
    FailJob,
    JobChange,
    ReportJobProgress,
    RetryJob,
    StartJob,
    SucceedJob,
)


async def _get[RequestT: BaseModel, ResultT: BaseModel](
    store: JobStorePort[RequestT, ResultT],
    job_id: JobId,
) -> JobRecord[RequestT, ResultT]:
    record = await store.get(job_id)
    if record is None:
        raise JobNotFound("Job not found")
    return record


async def _change[RequestT: BaseModel, ResultT: BaseModel](
    store: JobStorePort[RequestT, ResultT],
    job_id: JobId,
    change: JobChange[ResultT],
    *,
    attempt: int,
) -> JobRecord[RequestT, ResultT]:
    # Re-read after progress/cancellation races, never apply work to a later attempt.
    for _ in range(8):
        record = await _get(store, job_id)
        if record.attempt != attempt:
            raise JobTransitionError("The execution attempt is no longer current")
        try:
            return await store.change(job_id, change, expected_version=record.version)
        except JobVersionConflict:
            continue
    raise JobVersionConflict("Job changed repeatedly; retry the control operation")


class _MemoryContext[RequestT: BaseModel, ResultT: BaseModel](
    JobContext, CancellationToken
):
    def __init__(
        self, store: JobStorePort[RequestT, ResultT], job_id: JobId, attempt: int
    ) -> None:
        self._store = store
        self._job_id = job_id
        self._attempt = attempt

    @property
    def cancellation(self) -> CancellationToken:
        return self

    async def is_requested(self) -> bool:
        record = await _get(self._store, self._job_id)
        if record.attempt != self._attempt or record.status is not JobStatus.RUNNING:
            raise JobTransitionError("The execution context is no longer active")
        return record.cancellation_requested

    async def report_progress(self, progress: JobProgress) -> None:
        await _change(
            self._store,
            self._job_id,
            ReportJobProgress(progress),
            attempt=self._attempt,
        )


class InMemoryJobRunner[RequestT: BaseModel, ResultT: BaseModel](
    JobRunnerPort[RequestT, ResultT]
):
    """Local reference adapter: await run(job_id) to execute one queued attempt.

    The caller owns/awaits run() and any tasks it creates around it. Owner task
    cancellation records execution_interrupted then propagates CancelledError.
    No scheduler, durable recovery, thread/process isolation or worker pool.
    """

    def __init__(
        self,
        store: JobStorePort[RequestT, ResultT],
        handler: JobHandler[RequestT, ResultT],
    ) -> None:
        self._store = store
        self._handler = handler

    async def submit(self, request: JobRequest[RequestT]) -> JobId:
        return (await self._store.submit(request)).job_id

    async def cancel(self, job_id: JobId) -> JobRecord[RequestT, ResultT]:
        record = await _get(self._store, job_id)
        return await _change(self._store, job_id, CancelJob(), attempt=record.attempt)

    async def retry(self, job_id: JobId) -> JobRecord[RequestT, ResultT]:
        record = await _get(self._store, job_id)
        return await _change(self._store, job_id, RetryJob(), attempt=record.attempt)

    async def run(self, job_id: JobId) -> JobRecord[RequestT, ResultT]:
        queued = await _get(self._store, job_id)
        running = await self._store.change(
            job_id, StartJob(), expected_version=queued.version
        )
        context = _MemoryContext(self._store, job_id, running.attempt)
        try:
            result = await self._handler.execute(running.request.payload, context)
        except asyncio.CancelledError:
            await _change(
                self._store,
                job_id,
                FailJob(JobError(code="execution_interrupted")),
                attempt=running.attempt,
            )
            raise
        except JobCancellationRequested:
            if await context.is_requested():
                return await _change(
                    self._store,
                    job_id,
                    AcknowledgeJobCancellation(),
                    attempt=running.attempt,
                )
            return await self._fail(
                job_id, running.attempt, JobError(code="handler_failed")
            )
        except NotImplementedError:
            return await self._fail(
                job_id, running.attempt, JobError(code="handler_not_implemented")
            )
        except Exception:
            # This is the handler boundary: no exception text, repr or traceback
            # enters the public record. The owner instruments the handler if needed.
            return await self._fail(
                job_id, running.attempt, JobError(code="handler_failed")
            )
        # Persistence failures are outside the handler boundary. Do not report
        # an uncertain commit as a business failure, which could invite retries.
        try:
            return await _change(
                self._store,
                job_id,
                SucceedJob(JobResult(payload=result)),
                attempt=running.attempt,
            )
        except (ValueError, TypeError):
            return await self._fail(
                job_id, running.attempt, JobError(code="handler_failed")
            )

    async def _fail(
        self, job_id: JobId, attempt: int, error: JobError
    ) -> JobRecord[RequestT, ResultT]:
        return await _change(self._store, job_id, FailJob(error), attempt=attempt)
