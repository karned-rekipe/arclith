from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel, ValidationError

from arclith.domain.errors.job import JobTransitionError
from arclith.domain.models.job import (
    JobError,
    JobProgress,
    JobRecord,
    JobRequest,
    JobResult,
    JobStatus,
)
from arclith.domain.services.job_lifecycle import (
    AcknowledgeJobCancellation,
    CancelJob,
    FailJob,
    ReportJobProgress,
    RetryJob,
    StartJob,
    SucceedJob,
    transition_job,
)


class Payload(BaseModel):
    value: int = 1


NOW = datetime(2026, 9, 14, tzinfo=UTC)


def queued(**options):
    return JobRecord[Payload, Payload](
        request=JobRequest[Payload](payload=Payload(), **options),
        created_at=NOW,
        updated_at=NOW,
    )


def change(record, operation):
    return transition_job(
        record, operation, now=record.updated_at + timedelta(seconds=1)
    )


def states():
    initial = queued(max_attempts=2)
    running = change(initial, StartJob())
    return {
        JobStatus.QUEUED: initial,
        JobStatus.RUNNING: running,
        JobStatus.SUCCEEDED: change(running, SucceedJob(JobResult(payload=Payload()))),
        JobStatus.FAILED: change(running, FailJob(JobError(code="handler_failed"))),
        JobStatus.CANCELLED: change(initial, CancelJob()),
    }


@pytest.mark.parametrize("status", list(JobStatus))
@pytest.mark.parametrize(
    "operation,allowed",
    [
        (StartJob(), {JobStatus.QUEUED}),
        (RetryJob(), {JobStatus.FAILED}),
        (CancelJob(), {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.CANCELLED}),
        (SucceedJob(JobResult(payload=Payload())), {JobStatus.RUNNING}),
        (FailJob(JobError(code="handler_failed")), {JobStatus.RUNNING}),
        (ReportJobProgress(JobProgress(percent=50)), {JobStatus.RUNNING}),
        (AcknowledgeJobCancellation(), set()),
    ],
)
def test_transition_matrix(status, operation, allowed):
    record = states()[status]
    if status in allowed:
        updated = change(record, operation)
        assert updated.version in {record.version, record.version + 1}
        assert updated.updated_at.tzinfo is UTC
    else:
        with pytest.raises(JobTransitionError):
            change(record, operation)


def test_retry_keeps_identity_and_history():
    failed = states()[JobStatus.FAILED]
    retry = change(failed, RetryJob())
    assert retry.job_id == failed.job_id
    assert retry.attempt == 2 and retry.attempts == failed.attempts
    assert retry.error is None and retry.started_at is None
    succeeded = change(
        change(retry, StartJob()), SucceedJob(JobResult(payload=Payload(value=2)))
    )
    assert [a.status for a in succeeded.attempts] == [
        JobStatus.FAILED,
        JobStatus.SUCCEEDED,
    ]
    assert succeeded.result.payload.value == 2


def test_running_cancellation_requires_acknowledgement():
    running = states()[JobStatus.RUNNING]
    requested = change(running, CancelJob())
    assert requested.status is JobStatus.RUNNING and requested.cancellation_requested
    assert change(requested, CancelJob()) == requested
    cancelled = change(requested, AcknowledgeJobCancellation())
    assert cancelled.status is JobStatus.CANCELLED
    assert cancelled.attempts[0].status is JobStatus.CANCELLED


def test_handler_may_finish_before_acknowledging_cancellation():
    requested = change(states()[JobStatus.RUNNING], CancelJob())
    assert (
        change(requested, SucceedJob(JobResult(payload=Payload()))).status
        is JobStatus.SUCCEEDED
    )


def test_no_implicit_retry_and_optional_cancellation():
    failed = change(
        change(queued(), StartJob()), FailJob(JobError(code="handler_failed"))
    )
    with pytest.raises(JobTransitionError, match="exhausted"):
        change(failed, RetryJob())
    with pytest.raises(JobTransitionError, match="does not support"):
        change(queued(cancellable=False), CancelJob())


@pytest.mark.parametrize("percent", [-1, 101, float("nan"), float("inf"), "50", True])
def test_invalid_progress(percent):
    with pytest.raises(ValidationError):
        JobProgress(percent=percent)


@pytest.mark.parametrize("now", [NOW - timedelta(seconds=1), datetime(2026, 9, 14)])
def test_invalid_clock(now):
    with pytest.raises(ValueError, match="clock"):
        transition_job(queued(), StartJob(), now=now)


@pytest.mark.parametrize(
    "options",
    [
        {"max_attempts": 0},
        {"max_attempts": True},
        {"max_attempts": 101},
        {"retention_days": 0},
        {"retention_days": 3651},
        {"cancellable": "true"},
        {"idempotency_key": ""},
        {"idempotency_key": " spaced "},
        {"idempotency_key": "line\nbreak"},
        {"idempotency_key": "x" * 256},
    ],
)
def test_invalid_policy(options):
    with pytest.raises(ValidationError):
        queued(**options)


def test_snapshots_are_frozen_and_errors_are_bounded():
    with pytest.raises(ValidationError):
        queued().status = JobStatus.SUCCEEDED
    with pytest.raises(ValidationError):
        JobError(code="handler_failed", traceback="secret")
    assert JobError(code="handler_failed").message == "The job handler failed."
    assert JobError(code="handler_not_implemented").message
    assert JobError(code="execution_interrupted").message


@pytest.mark.parametrize(
    "updates",
    [
        {"updated_at": NOW - timedelta(seconds=1)},
        {"attempt": 2},
        {"result": JobResult(payload=Payload())},
        {"error": JobError(code="handler_failed")},
        {"finished_at": NOW},
        {"status": JobStatus.RUNNING},
        {"started_at": NOW},
        {"progress": JobProgress(percent=50)},
        {"schema_version": True},
    ],
)
def test_invalid_record_combinations(updates):
    data = queued().model_dump()
    with pytest.raises(ValidationError):
        JobRecord[Payload, Payload].model_validate({**data, **updates})


def test_attempt_outcome_and_temporal_invariants():
    from arclith.domain.models.job import JobAttempt

    with pytest.raises(ValidationError):
        JobAttempt(number=1, status=JobStatus.FAILED, started_at=NOW, finished_at=NOW)
    with pytest.raises(ValidationError):
        JobAttempt(
            number=1,
            status=JobStatus.SUCCEEDED,
            started_at=NOW,
            finished_at=NOW - timedelta(seconds=1),
        )
    failed = states()[JobStatus.FAILED]
    for updates in (
        {"attempts": ()},
        {"finished_at": NOW},
        {"started_at": NOW - timedelta(days=1)},
    ):
        with pytest.raises(ValidationError):
            JobRecord[Payload, Payload].model_validate(
                {**failed.model_dump(), **updates}
            )
