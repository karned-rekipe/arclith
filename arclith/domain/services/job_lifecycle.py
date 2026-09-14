"""The closed job transition algebra shared by stores and runners."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from arclith.domain.errors.job import JobTransitionError
from arclith.domain.models.job import (
    JobAttempt,
    JobError,
    JobProgress,
    JobRecord,
    JobResult,
    JobStatus,
)


@dataclass(frozen=True)
class StartJob:
    pass


@dataclass(frozen=True)
class SucceedJob[ResultT: BaseModel]:
    result: JobResult[ResultT]


@dataclass(frozen=True)
class FailJob:
    error: JobError


@dataclass(frozen=True)
class CancelJob:
    pass


@dataclass(frozen=True)
class AcknowledgeJobCancellation:
    pass


@dataclass(frozen=True)
class RetryJob:
    pass


@dataclass(frozen=True)
class ReportJobProgress:
    progress: JobProgress


type JobChange[ResultT: BaseModel] = (
    StartJob
    | SucceedJob[ResultT]
    | FailJob
    | CancelJob
    | AcknowledgeJobCancellation
    | RetryJob
    | ReportJobProgress
)


def transition_job[RequestT: BaseModel, ResultT: BaseModel](
    record: JobRecord[RequestT, ResultT],
    change: JobChange[ResultT],
    *,
    now: datetime,
) -> JobRecord[RequestT, ResultT]:
    """Apply one validated change; never accept arbitrary field replacements."""
    if now.utcoffset() is None or now < record.updated_at:
        raise ValueError("Job clock must be timezone-aware and monotonic")
    now = now.astimezone(UTC)
    updates = _change_fields(record, change, now)
    if not updates:
        return record.model_copy(deep=True)
    data = {name: getattr(record, name) for name in type(record).model_fields}
    data.update(updates, version=record.version + 1, updated_at=now)
    return type(record).model_validate(data)


def _require_status(status: JobStatus, expected: JobStatus) -> None:
    if status is not expected:
        raise JobTransitionError(
            f"Operation requires {expected.value}; job is {status.value}"
        )


def _change_fields[RequestT: BaseModel, ResultT: BaseModel](
    record: JobRecord[RequestT, ResultT],
    change: JobChange[ResultT],
    now: datetime,
) -> dict[str, object]:
    if isinstance(change, StartJob):
        _require_status(record.status, JobStatus.QUEUED)
        return {"status": JobStatus.RUNNING, "started_at": now}
    if isinstance(change, RetryJob):
        _require_status(record.status, JobStatus.FAILED)
        if record.attempt >= record.request.max_attempts:
            raise JobTransitionError("Job max_attempts exhausted")
        return {
            "status": JobStatus.QUEUED,
            "attempt": record.attempt + 1,
            "started_at": None,
            "finished_at": None,
            "error": None,
            "progress": None,
            "cancellation_requested": False,
        }
    if isinstance(change, CancelJob):
        return _cancel_fields(record, now)
    _require_status(record.status, JobStatus.RUNNING)
    if isinstance(change, ReportJobProgress):
        return {"progress": JobProgress.model_validate(change.progress.model_dump())}
    if isinstance(change, SucceedJob):
        return _finish_fields(record, JobStatus.SUCCEEDED, now) | {
            "result": change.result
        }
    if isinstance(change, FailJob):
        return _finish_fields(record, JobStatus.FAILED, now, error=change.error)
    if isinstance(change, AcknowledgeJobCancellation):
        if not record.cancellation_requested:
            raise JobTransitionError("Cancellation has not been requested")
        return _finish_fields(record, JobStatus.CANCELLED, now)
    raise TypeError("Unsupported job change")


def _cancel_fields[RequestT: BaseModel, ResultT: BaseModel](
    record: JobRecord[RequestT, ResultT],
    now: datetime,
) -> dict[str, object]:
    if not record.request.cancellable:
        raise JobTransitionError("Job does not support cancellation")
    if record.status is JobStatus.CANCELLED:
        return {}
    if record.status is JobStatus.QUEUED:
        return {
            "status": JobStatus.CANCELLED,
            "finished_at": now,
            "cancellation_requested": True,
        }
    _require_status(record.status, JobStatus.RUNNING)
    return {} if record.cancellation_requested else {"cancellation_requested": True}


def _finish_fields[RequestT: BaseModel, ResultT: BaseModel](
    record: JobRecord[RequestT, ResultT],
    status: Literal[JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED],
    now: datetime,
    *,
    error: JobError | None = None,
) -> dict[str, object]:
    if record.started_at is None:
        raise JobTransitionError("Attempt has not started")
    attempt = JobAttempt(
        number=record.attempt,
        status=status,
        started_at=record.started_at,
        finished_at=now,
        error=error,
    )
    return {
        "status": status,
        "finished_at": now,
        "error": error,
        "attempts": (*record.attempts, attempt),
    }
