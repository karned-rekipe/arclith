import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import BaseModel, Field, SecretStr, field_serializer

from arclith.adapters.outbound.memory.job_runner import InMemoryJobRunner
from arclith.adapters.outbound.memory.job_store import InMemoryJobStore
from arclith.application.services.job_service import JobService
from arclith.domain.errors.job import (
    JobCancellationRequested,
    JobIdempotencyConflict,
    JobNotFound,
    JobResultUnavailable,
    JobTransitionError,
    JobVersionConflict,
)
from arclith.domain.models.job import JobProgress, JobRequest, JobResult, JobStatus
from arclith.domain.ports.outbound.job_runner import JobHandler
from arclith.domain.services.job_lifecycle import StartJob, SucceedJob


class Request(BaseModel):
    values: list[int] = Field(default_factory=lambda: [1])


class Result(BaseModel):
    total: int


class SumHandler(JobHandler[Request, Result]):
    async def execute(self, request, context):
        await context.cancellation.checkpoint()
        await context.report_progress(JobProgress(percent=100))
        return Result(total=sum(request.values))


def setup(handler=None, **options):
    store = InMemoryJobStore(Request, Result, **options)
    runner = InMemoryJobRunner(store, handler or SumHandler())
    return store, runner, JobService(runner, store)


async def test_success_and_result_access():
    store, runner, service = setup()
    job_id = await service.submit(JobRequest(payload=Request(values=[1, 2])))
    assert (await service.get_status(job_id)).status is JobStatus.QUEUED
    with pytest.raises(JobResultUnavailable):
        await service.get_result(job_id)
    result = await runner.run(job_id)
    assert result.status is JobStatus.SUCCEEDED
    assert result.progress.percent == 100
    assert (await service.get_result(job_id)).payload.total == 3
    assert result.attempts[0].number == 1
    assert (await store.get(job_id)).request.payload.values == [1, 2]


async def test_concurrent_submissions_are_idempotent_and_isolated():
    store, runner, service = setup()
    request = JobRequest(payload=Request(), idempotency_key="same")
    ids = await asyncio.gather(*(service.submit(request) for _ in range(30)))
    assert len(set(ids)) == 1
    request.payload.values.append(99)
    snapshot = await store.get(ids[0])
    snapshot.request.payload.values.append(88)
    assert (await store.get(ids[0])).request.payload.values == [1]
    with pytest.raises(JobIdempotencyConflict):
        await service.submit(request)
    with pytest.raises(JobIdempotencyConflict):
        await service.submit(
            JobRequest(payload=Request(), idempotency_key="same", max_attempts=2)
        )
    await runner.run(ids[0])
    assert (
        await service.submit(JobRequest(payload=Request(), idempotency_key="same"))
        == ids[0]
    )
    assert await service.submit(JobRequest(payload=Request())) != ids[0]


async def test_an_attempt_is_claimed_only_once():
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    class Paused(JobHandler[Request, Result]):
        async def execute(self, request, context):
            calls.append(request)
            entered.set()
            await release.wait()
            return Result(total=1)

    _, runner, service = setup(Paused())
    job_id = await service.submit(JobRequest(payload=Request()))
    task = asyncio.create_task(runner.run(job_id))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert (await service.get_status(job_id)).status is JobStatus.RUNNING
        with pytest.raises((JobTransitionError, JobVersionConflict)):
            await runner.run(job_id)
    finally:
        release.set()
        await task
    assert len(calls) == 1


async def test_queued_cancellation_never_executes():
    _, runner, service = setup()
    job_id = await service.submit(JobRequest(payload=Request()))
    assert (await service.cancel(job_id)).status is JobStatus.CANCELLED
    assert (await service.cancel(job_id)).status is JobStatus.CANCELLED
    with pytest.raises(JobTransitionError):
        await runner.run(job_id)


async def test_running_cancellation_and_stale_context():
    entered, release = asyncio.Event(), asyncio.Event()
    contexts = []

    class Cooperative(JobHandler[Request, Result]):
        async def execute(self, request, context):
            contexts.append(context)
            entered.set()
            await release.wait()
            await context.cancellation.checkpoint()
            return Result(total=1)

    _, runner, service = setup(Cooperative())
    job_id = await service.submit(JobRequest(payload=Request()))
    task = asyncio.create_task(runner.run(job_id))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert (await service.cancel(job_id)).status is JobStatus.RUNNING
    finally:
        release.set()
        final = await task
    assert final.status is JobStatus.CANCELLED
    with pytest.raises(JobTransitionError):
        await contexts[0].cancellation.is_requested()
    with pytest.raises(JobTransitionError):
        await contexts[0].report_progress(JobProgress(percent=10))


@pytest.mark.parametrize(
    "failure,code",
    [
        (RuntimeError("password=do-not-store"), "handler_failed"),
        (NotImplementedError("secret"), "handler_not_implemented"),
        (JobCancellationRequested("not actually requested"), "handler_failed"),
    ],
)
async def test_failure_is_bounded_and_retry_explicit(failure, code):
    calls = []

    class FailsOnce(JobHandler[Request, Result]):
        async def execute(self, request, context):
            calls.append(1)
            if len(calls) == 1:
                raise failure
            return Result(total=2)

    _, runner, service = setup(FailsOnce())
    job_id = await service.submit(JobRequest(payload=Request(), max_attempts=2))
    with pytest.raises(JobTransitionError):
        await service.retry(job_id)
    failed = await runner.run(job_id)
    assert failed.status is JobStatus.FAILED and failed.error.code == code
    assert "secret" not in failed.model_dump_json()
    assert "password" not in failed.model_dump_json()
    assert calls == [1]
    retried = await service.retry(job_id)
    assert retried.job_id == job_id and retried.attempt == 2
    assert (await runner.run(job_id)).result.payload.total == 2


async def test_owner_cancellation_is_collected_and_propagated():
    entered = asyncio.Event()

    class Waiting(JobHandler[Request, Result]):
        async def execute(self, request, context):
            entered.set()
            await asyncio.Event().wait()

    _, runner, service = setup(Waiting())
    job_id = await service.submit(JobRequest(payload=Request()))
    task = asyncio.create_task(runner.run(job_id))
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await service.get_status(job_id)).error.code == "execution_interrupted"


async def test_not_found_and_version_conflicts():
    store, runner, service = setup()
    assert await store.get(uuid4()) is None
    for operation in (
        service.get_status,
        service.get_result,
        service.cancel,
        service.retry,
        runner.run,
    ):
        with pytest.raises(JobNotFound):
            await operation(uuid4())
    with pytest.raises(JobNotFound):
        await store.change(uuid4(), StartJob(), expected_version=1)
    job_id = await service.submit(JobRequest(payload=Request()))
    with pytest.raises(JobVersionConflict):
        await store.change(job_id, StartJob(), expected_version=2)
    for version in (True, 0, "1"):
        with pytest.raises(ValueError):
            await store.change(job_id, StartJob(), expected_version=version)


async def test_retention_purges_terminal_jobs_and_keys_only():
    clock = [datetime(2026, 9, 14, tzinfo=UTC)]
    store, runner, service = setup(clock=lambda: clock[0])
    request = JobRequest(payload=Request(), idempotency_key="reuse", retention_days=1)
    job_id = await service.submit(request)
    queued_id = await service.submit(JobRequest(payload=Request(), retention_days=1))
    await runner.run(job_id)
    clock[0] += timedelta(hours=23)
    assert await store.purge_expired() == 0
    clock[0] += timedelta(hours=1)
    assert await store.purge_expired() == 1
    assert await store.get(job_id) is None and await store.get(queued_id) is not None
    assert await service.submit(request) != job_id


async def test_hidden_fields_are_not_hidden_from_idempotency():
    class Hidden(BaseModel):
        value: str = Field(exclude=True, alias="external")

        @field_serializer("value")
        def hide(self, value):
            return "hidden"

    store = InMemoryJobStore(Hidden, Result)
    first = await store.submit(
        JobRequest(payload=Hidden(external="first"), idempotency_key="key")
    )
    with pytest.raises(JobIdempotencyConflict):
        await store.submit(
            JobRequest(payload=Hidden(external="second"), idempotency_key="key")
        )
    started = await store.change(
        first.job_id, StartJob(), expected_version=first.version
    )
    assert started.request.payload.value == "first"


@pytest.mark.parametrize(
    "value",
    [
        SecretStr("secret"),
        object(),
        float("nan"),
        {1: "not a string key"},
        "x" * 70_000,
    ],
)
async def test_non_portable_or_oversized_payload_rejected(value):
    class Payload(BaseModel):
        value: object

    store = InMemoryJobStore(Payload, Result)
    with pytest.raises(ValueError):
        await store.submit(JobRequest(payload=Payload(value=value)))


async def test_invalid_result_fails_without_leaking_validation_error():
    class Wrong(JobHandler[Request, Result]):
        async def execute(self, request, context):
            return Request()

    _, runner, service = setup(Wrong())
    record = await runner.run(await service.submit(JobRequest(payload=Request())))
    assert record.status is JobStatus.FAILED
    assert record.error.code == "handler_failed"


async def test_result_snapshot_is_isolated():
    store = InMemoryJobStore(Request, Request)
    record = await store.submit(JobRequest(payload=Request()))
    record = await store.change(
        record.job_id, StartJob(), expected_version=record.version
    )
    result = Request()
    record = await store.change(
        record.job_id,
        SucceedJob(JobResult(payload=result)),
        expected_version=record.version,
    )
    result.values.append(9)
    record.result.payload.values.append(8)
    assert (await store.get(record.job_id)).result.payload.values == [1]


async def test_completion_store_failure_is_not_classified_as_handler_failure():
    class Unavailable(InMemoryJobStore[Request, Result]):
        async def change(self, job_id, change, *, expected_version):
            if isinstance(change, SucceedJob):
                raise OSError("commit outcome uncertain")
            return await super().change(
                job_id, change, expected_version=expected_version
            )

    store = Unavailable(Request, Result)
    runner = InMemoryJobRunner(store, SumHandler())
    job_id = await runner.submit(JobRequest(payload=Request()))
    with pytest.raises(OSError, match="uncertain"):
        await runner.run(job_id)
    assert (await store.get(job_id)).status is JobStatus.RUNNING


async def test_cas_race_is_retried_without_rerunning_handler():
    class Contended(InMemoryJobStore[Request, Result]):
        conflicts = 0

        async def change(self, job_id, change, *, expected_version):
            if not isinstance(change, StartJob) and self.conflicts < 2:
                self.conflicts += 1
                raise JobVersionConflict("concurrent progress")
            return await super().change(
                job_id, change, expected_version=expected_version
            )

    store = Contended(Request, Result)
    runner = InMemoryJobRunner(store, SumHandler())
    record = await runner.run(await runner.submit(JobRequest(payload=Request())))
    assert record.status is JobStatus.SUCCEEDED and store.conflicts == 2


async def test_old_attempt_context_cannot_modify_a_retry():
    contexts = []

    class Failed(JobHandler[Request, Result]):
        async def execute(self, request, context):
            contexts.append(context)
            raise RuntimeError("failure")

    _, runner, service = setup(Failed())
    job_id = await service.submit(JobRequest(payload=Request(), max_attempts=2))
    await runner.run(job_id)
    await service.retry(job_id)
    with pytest.raises(JobTransitionError, match="no longer current"):
        await contexts[0].report_progress(JobProgress(percent=5))


async def test_schema_and_unsafe_request_values_revalidated():
    store, _, _ = setup()
    request = JobRequest(payload=Request()).model_copy(update={"max_attempts": True})
    with pytest.raises(ValueError):
        await store.submit(request)
    request = JobRequest(payload=Request()).model_copy(update={"schema_version": True})
    with pytest.raises(ValueError):
        await store.submit(request)
    with pytest.raises(ValueError):
        await store.submit(JobRequest(payload=Result(total=1)))
    record = await store.submit(JobRequest(payload=Request()))
    record = await store.change(
        record.job_id, StartJob(), expected_version=record.version
    )
    invalid = JobResult(payload=Result(total=1)).model_copy(
        update={"schema_version": 2}
    )
    with pytest.raises(ValueError):
        await store.change(
            record.job_id, SucceedJob(invalid), expected_version=record.version
        )


async def test_nesting_and_invalid_clock_rejected():
    class Nested(BaseModel):
        value: object

    value = None
    for _ in range(35):
        value = [value]
    with pytest.raises(ValueError, match="nesting"):
        await InMemoryJobStore(Nested, Result).submit(
            JobRequest(payload=Nested(value=value))
        )
    naive = InMemoryJobStore(Request, Result, clock=lambda: datetime(2026, 9, 14))
    with pytest.raises(ValueError):
        await naive.submit(JobRequest(payload=Request()))
    with pytest.raises(ValueError):
        await naive.purge_expired()
