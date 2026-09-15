"""Versioned sequential execution state, separate from business aggregates."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
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

from arclith.domain.models.job import JobProgress

type WorkflowId = UUID
type WorkflowName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=80)]
type WorkflowModelName = Annotated[
    str, Field(pattern=r"^[A-Z][A-Za-z0-9_]*$", max_length=80)
]


class WorkflowModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", allow_inf_nan=False, revalidate_instances="always"
    )

    @field_validator("schema_version", mode="before", check_fields=False)
    @classmethod
    def validate_schema_version(cls, value: object) -> int:
        if type(value) is not int or value != 1:
            raise ValueError("Workflow schema_version must be integer 1")
        return value


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WorkflowStepDefinition(WorkflowModel):
    name: WorkflowName
    max_attempts: int = Field(default=1, ge=1, le=100, strict=True)


class WorkflowDefinition(WorkflowModel):
    schema_version: Literal[1] = 1
    name: WorkflowName
    version: int = Field(default=1, ge=1, le=1_000_000, strict=True)
    context: WorkflowModelName
    result: WorkflowModelName
    steps: tuple[WorkflowStepDefinition, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_names(self) -> Self:
        if len({step.name for step in self.steps}) != len(self.steps):
            raise ValueError("Workflow step names must be unique")
        if self.context == self.result:
            raise ValueError("Workflow context and result require distinct names")
        return self


class WorkflowFailure(WorkflowModel):
    code: Literal[
        "step_failed", "step_not_implemented", "execution_interrupted", "result_failed"
    ]


class WorkflowStepRecord(WorkflowModel):
    name: WorkflowName
    status: WorkflowStepStatus = WorkflowStepStatus.PENDING
    attempts: int = Field(default=0, ge=0, le=100, strict=True)
    error: WorkflowFailure | None = None

    @model_validator(mode="after")
    def outcome(self) -> Self:
        if (self.status is WorkflowStepStatus.PENDING) != (self.attempts == 0):
            raise ValueError("Only pending steps have zero attempts")
        if (self.status is WorkflowStepStatus.FAILED) != (self.error is not None):
            raise ValueError("Only failed steps have an error")
        return self


type WorkflowEventKind = Literal[
    "started",
    "resumed",
    "step_started",
    "step_succeeded",
    "failed",
    "cancel_requested",
    "cancelled",
    "completed",
]


class WorkflowEvent(WorkflowModel):
    sequence: int = Field(ge=1, strict=True)
    kind: WorkflowEventKind
    step: WorkflowName | None = None
    at: AwareDatetime


class WorkflowInstance[ContextT: BaseModel, ResultT: BaseModel](WorkflowModel):
    schema_version: Literal[1] = 1
    workflow_id: UUID = Field(default_factory=uuid7)
    definition: WorkflowDefinition
    definition_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    context: ContextT
    status: WorkflowStatus = WorkflowStatus.PENDING
    version: int = Field(default=1, ge=1, strict=True)
    checkpoint: int = Field(default=0, ge=0, le=100, strict=True)
    steps: tuple[WorkflowStepRecord, ...] = Field(min_length=1, max_length=100)
    cancellation_requested: bool = Field(default=False, strict=True)
    result: ResultT | None = None
    error: WorkflowFailure | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    events: tuple[WorkflowEvent, ...] = Field(default=(), max_length=200)

    @property
    def progress(self) -> JobProgress:
        return JobProgress(completed=self.checkpoint, total=len(self.steps))

    @field_validator("created_at", "updated_at", "finished_at")
    @classmethod
    def utc(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def lifecycle(self) -> Self:
        self._validate_steps()
        self._validate_timestamps()
        self._validate_outcome()
        return self

    def _validate_timestamps(self) -> None:
        if self.updated_at < self.created_at:
            raise ValueError("Workflow timestamps must be monotonic")
        terminal = self.status in {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }
        if terminal != (self.finished_at is not None):
            raise ValueError("Only terminal workflows have finished_at")
        if self.finished_at is not None and self.finished_at != self.updated_at:
            raise ValueError("Terminal timestamp must match updated_at")

    def _validate_outcome(self) -> None:
        if (self.status is WorkflowStatus.COMPLETED) != (self.result is not None):
            raise ValueError("Only completed workflows have a result")
        if (self.status is WorkflowStatus.FAILED) != (self.error is not None):
            raise ValueError("Only failed workflows have an error")
        if self.status is WorkflowStatus.COMPLETED and self.checkpoint != len(
            self.steps
        ):
            raise ValueError("Completion requires every checkpoint")
        if self.status is WorkflowStatus.CANCELLED and not self.cancellation_requested:
            raise ValueError("Cancellation requires a request")
        if self.status is WorkflowStatus.PENDING and any(
            step.attempts for step in self.steps
        ):
            raise ValueError("Pending workflows cannot have executed steps")

    def _validate_steps(self) -> None:
        if len(self.steps) != len(self.definition.steps) or self.checkpoint > len(
            self.steps
        ):
            raise ValueError("Steps/checkpoint must match the definition")
        for index, (step, definition) in enumerate(
            zip(self.steps, self.definition.steps, strict=True)
        ):
            if step.name != definition.name or step.attempts > definition.max_attempts:
                raise ValueError(
                    "Step identity or attempt budget differs from definition"
                )
            self._validate_step_position(index, step)

    def _validate_step_position(self, index: int, step: WorkflowStepRecord) -> None:
        expected = (
            WorkflowStepStatus.SUCCEEDED
            if index < self.checkpoint
            else WorkflowStepStatus.PENDING
        )
        if index != self.checkpoint and step.status is not expected:
            raise ValueError("Confirmed steps must form a contiguous prefix")
        if index == self.checkpoint and step.status is WorkflowStepStatus.SUCCEEDED:
            raise ValueError("Succeeded step requires its checkpoint")
