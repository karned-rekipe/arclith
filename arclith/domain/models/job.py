"""Versioned execution data, independent of providers and business entities."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from uuid6 import uuid7

type JobId = UUID


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
        revalidate_instances="always",
    )

    @field_validator("schema_version", mode="before", check_fields=False)
    @classmethod
    def validate_schema_version(cls, value: object) -> int:
        if type(value) is not int or value != 1:
            raise ValueError("Job schema_version must be integer 1")
        return value


class JobProgress(JobModel):
    """Percentage or counters; an unknown total never implies a percentage."""

    percent: float | None = Field(default=None, ge=0, le=100, strict=True)
    completed: int | None = Field(default=None, ge=0, le=10**12, strict=True)
    total: int | None = Field(default=None, ge=0, le=10**12, strict=True)

    @model_validator(mode="after")
    def validate_counters(self) -> Self:
        if self.percent is None and self.completed is None:
            raise ValueError("Progress requires a percentage or completed counter")
        if self.total is not None and (
            self.completed is None or self.completed > self.total
        ):
            raise ValueError("Progress completed must not exceed its known total")
        return self


class JobError(JobModel):
    """Public error codes have fixed messages; exception text is never stored."""

    schema_version: Literal[1] = 1
    code: Literal["handler_failed", "handler_not_implemented", "execution_interrupted"]

    @property
    def message(self) -> str:
        return {
            "handler_failed": "The job handler failed.",
            "handler_not_implemented": "The job handler must be implemented.",
            "execution_interrupted": "The execution owner interrupted this attempt.",
        }[self.code]


class JobRequest[RequestT: BaseModel](JobModel):
    schema_version: Literal[1] = 1
    payload: RequestT
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)
    cancellable: bool = Field(default=True, strict=True)
    max_attempts: int = Field(default=1, ge=1, le=100, strict=True)
    retention_days: int = Field(default=7, ge=1, le=3650, strict=True)

    @field_validator("idempotency_key")
    @classmethod
    def validate_key(cls, value: str | None) -> str | None:
        if value is not None and (value != value.strip() or not value.isprintable()):
            raise ValueError(
                "Idempotency key must be printable without surrounding whitespace"
            )
        return value


class JobResult[ResultT: BaseModel](JobModel):
    schema_version: Literal[1] = 1
    payload: ResultT


class JobAttempt(JobModel):
    number: int = Field(ge=1, le=100, strict=True)
    status: Literal[JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED]
    started_at: AwareDatetime
    finished_at: AwareDatetime
    error: JobError | None = None

    @field_validator("started_at", "finished_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("An attempt cannot finish before it starts")
        if (self.status is JobStatus.FAILED) != (self.error is not None):
            raise ValueError("Only failed attempts carry an error")
        return self


class JobRecord[RequestT: BaseModel, ResultT: BaseModel](JobModel):
    schema_version: Literal[1] = 1
    job_id: UUID = Field(default_factory=uuid7)
    request: JobRequest[RequestT]
    status: JobStatus = JobStatus.QUEUED
    version: int = Field(default=1, ge=1, strict=True)
    attempt: int = Field(default=1, ge=1, le=100, strict=True)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    cancellation_requested: bool = Field(default=False, strict=True)
    progress: JobProgress | None = None
    result: JobResult[ResultT] | None = None
    error: JobError | None = None
    attempts: tuple[JobAttempt, ...] = ()

    @field_validator("created_at", "updated_at", "started_at", "finished_at")
    @classmethod
    def utc(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        self._validate_timestamps()
        self._validate_status_fields()
        self._validate_execution_fields()
        self._validate_attempts()
        return self

    def _validate_status_fields(self) -> None:
        if self.attempt > self.request.max_attempts:
            raise ValueError("Job attempt exceeds max_attempts")
        if (self.status is JobStatus.SUCCEEDED) != (self.result is not None):
            raise ValueError("Only succeeded jobs carry a result")
        if (self.status is JobStatus.FAILED) != (self.error is not None):
            raise ValueError("Only failed jobs carry an error")
        terminal = self.status in {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }
        if terminal != (self.finished_at is not None):
            raise ValueError("Only terminal jobs have finished_at")

    def _validate_execution_fields(self) -> None:
        if self.status in {JobStatus.RUNNING, JobStatus.SUCCEEDED, JobStatus.FAILED}:
            if self.started_at is None:
                raise ValueError("An executed job requires started_at")
        if self.status is JobStatus.QUEUED and self.started_at is not None:
            raise ValueError("Queued jobs have not started their current attempt")
        if self.cancellation_requested and not self.request.cancellable:
            raise ValueError("This job does not support cancellation")
        if self.status is JobStatus.CANCELLED and not self.cancellation_requested:
            raise ValueError("Cancelled jobs require a cancellation request")

    def _validate_timestamps(self) -> None:
        if self.updated_at < self.created_at:
            raise ValueError("Job timestamps must be monotonic")
        if (
            self.started_at is not None
            and not self.created_at <= self.started_at <= self.updated_at
        ):
            raise ValueError("Job start must be within its lifetime")
        if self.finished_at is not None and self.finished_at != self.updated_at:
            raise ValueError("Terminal jobs cannot change after finishing")
        if self.progress is not None and self.started_at is None:
            raise ValueError("Progress requires a started attempt")

    def _validate_attempts(self) -> None:
        terminal = self.status in {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }
        completed = (
            self.attempt
            if terminal and self.started_at is not None
            else self.attempt - 1
        )
        if tuple(item.number for item in self.attempts) != tuple(
            range(1, completed + 1)
        ):
            raise ValueError("Attempt history must be contiguous and complete")
        if any(
            item.status is not JobStatus.FAILED
            for item in self.attempts[: self.attempt - 1]
        ):
            raise ValueError("Only failed attempts can be retried")
        if terminal and self.started_at is not None:
            last = self.attempts[-1]
            if (last.status, last.started_at, last.finished_at, last.error) != (
                self.status,
                self.started_at,
                self.finished_at,
                self.error,
            ):
                raise ValueError("Latest attempt must match the terminal job outcome")
