"""Closed transitions shared by workflow stores and execution adapters."""

from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel

from arclith.domain.errors.workflow import WorkflowTransitionError
from arclith.domain.models.workflow import (
    WorkflowEvent,
    WorkflowEventKind,
    WorkflowFailure,
    WorkflowInstance,
    WorkflowStatus,
    WorkflowStepRecord,
    WorkflowStepStatus,
)


@dataclass(frozen=True)
class StartWorkflow:
    resume: bool = False


@dataclass(frozen=True)
class BeginWorkflowStep:
    pass


@dataclass(frozen=True)
class CommitWorkflowStep[ContextT: BaseModel]:
    context: ContextT


@dataclass(frozen=True)
class CompleteWorkflow[ResultT: BaseModel]:
    result: ResultT


@dataclass(frozen=True)
class FailWorkflow:
    error: WorkflowFailure


@dataclass(frozen=True)
class CancelWorkflow:
    pass


@dataclass(frozen=True)
class AcknowledgeWorkflowCancellation:
    pass


type WorkflowChange[ContextT: BaseModel, ResultT: BaseModel] = (
    StartWorkflow
    | BeginWorkflowStep
    | CommitWorkflowStep[ContextT]
    | CompleteWorkflow[ResultT]
    | FailWorkflow
    | CancelWorkflow
    | AcknowledgeWorkflowCancellation
)


def transition_workflow[ContextT: BaseModel, ResultT: BaseModel](
    record: WorkflowInstance[ContextT, ResultT],
    change: WorkflowChange[ContextT, ResultT],
    *,
    now: datetime,
) -> WorkflowInstance[ContextT, ResultT]:
    if now.utcoffset() is None or now < record.updated_at:
        raise ValueError("Workflow clock must be aware and monotonic")
    now = now.astimezone(UTC)
    updates, kind = _fields(record, change, now)
    if not updates:
        return record.model_copy(deep=True)
    step = (
        record.steps[record.checkpoint].name
        if record.checkpoint < len(record.steps)
        else None
    )
    event = WorkflowEvent(kind=kind, sequence=record.version + 1, step=step, at=now)
    data = {name: getattr(record, name) for name in type(record).model_fields}
    data.update(
        updates,
        version=record.version + 1,
        updated_at=now,
        events=(*record.events, event)[-200:],
    )
    return type(record).model_validate(data)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise WorkflowTransitionError(message)


def _start[ContextT: BaseModel, ResultT: BaseModel](
    record: WorkflowInstance[ContextT, ResultT], resume: bool
) -> dict[str, object]:
    if resume:
        _require(
            record.status in {WorkflowStatus.FAILED, WorkflowStatus.RUNNING},
            "Resume requires failed or unconfirmed execution",
        )
        if record.checkpoint < len(record.steps) and not record.cancellation_requested:
            _require(
                record.steps[record.checkpoint].attempts
                < record.definition.steps[record.checkpoint].max_attempts,
                "Workflow step max_attempts exhausted",
            )
    else:
        _require(
            record.status is WorkflowStatus.PENDING, "Run requires a pending workflow"
        )
    updates: dict[str, object] = {
        "status": WorkflowStatus.RUNNING,
        "finished_at": None,
        "error": None,
    }
    if resume and record.checkpoint < len(record.steps):
        current = record.steps[record.checkpoint]
        if current.status is WorkflowStepStatus.RUNNING:
            updates["steps"] = _replace_step(
                record,
                WorkflowStepRecord(
                    name=current.name,
                    attempts=current.attempts,
                    status=WorkflowStepStatus.FAILED,
                    error=WorkflowFailure(code="execution_interrupted"),
                ),
            )
    return updates


def _replace_step[ContextT: BaseModel, ResultT: BaseModel](
    record: WorkflowInstance[ContextT, ResultT], step: WorkflowStepRecord
) -> tuple[WorkflowStepRecord, ...]:
    return (
        *record.steps[: record.checkpoint],
        step,
        *record.steps[record.checkpoint + 1 :],
    )


def _fields[ContextT: BaseModel, ResultT: BaseModel](
    record: WorkflowInstance[ContextT, ResultT],
    change: WorkflowChange[ContextT, ResultT],
    now: datetime,
) -> tuple[dict[str, object], WorkflowEventKind]:
    if isinstance(change, StartWorkflow):
        return _start(record, change.resume), "resumed" if change.resume else "started"
    if isinstance(change, CancelWorkflow):
        return _cancel_fields(record, now)
    _require(
        record.status is WorkflowStatus.RUNNING, "Operation requires a running workflow"
    )
    if isinstance(change, AcknowledgeWorkflowCancellation):
        _require(record.cancellation_requested, "Cancellation has not been requested")
        return {"status": WorkflowStatus.CANCELLED, "finished_at": now}, "cancelled"
    if isinstance(change, FailWorkflow):
        return _fail(record, change.error, now), "failed"
    if isinstance(change, CompleteWorkflow):
        _require(
            record.checkpoint == len(record.steps),
            "Every step must be confirmed before completion",
        )
        if record.cancellation_requested:
            return {"status": WorkflowStatus.CANCELLED, "finished_at": now}, "cancelled"
        return {
            "status": WorkflowStatus.COMPLETED,
            "result": change.result,
            "finished_at": now,
        }, "completed"
    return _step_fields(record, change)


def _step_fields[ContextT: BaseModel, ResultT: BaseModel](
    record: WorkflowInstance[ContextT, ResultT],
    change: WorkflowChange[ContextT, ResultT],
) -> tuple[dict[str, object], WorkflowEventKind]:
    _require(record.checkpoint < len(record.steps), "No remaining workflow step")
    current = record.steps[record.checkpoint]
    if isinstance(change, BeginWorkflowStep):
        _require(
            current.status in {WorkflowStepStatus.PENDING, WorkflowStepStatus.FAILED},
            "Resume is required before restarting an unconfirmed step",
        )
        _require(not record.cancellation_requested, "Cancellation prevents a new step")
        _require(
            current.attempts < record.definition.steps[record.checkpoint].max_attempts,
            "Workflow step max_attempts exhausted",
        )
        step = WorkflowStepRecord(
            name=current.name,
            status=WorkflowStepStatus.RUNNING,
            attempts=current.attempts + 1,
        )
        return {"steps": _replace_step(record, step)}, "step_started"
    if isinstance(change, CommitWorkflowStep):
        _require(
            current.status is WorkflowStepStatus.RUNNING,
            "Only a running step can be checkpointed",
        )
        step = WorkflowStepRecord(
            name=current.name,
            status=WorkflowStepStatus.SUCCEEDED,
            attempts=current.attempts,
        )
        return {
            "steps": _replace_step(record, step),
            "context": change.context,
            "checkpoint": record.checkpoint + 1,
        }, "step_succeeded"
    raise TypeError("Unsupported workflow change")


def _fail[ContextT: BaseModel, ResultT: BaseModel](
    record: WorkflowInstance[ContextT, ResultT], error: WorkflowFailure, now: datetime
) -> dict[str, object]:
    updates: dict[str, object] = {
        "status": WorkflowStatus.FAILED,
        "finished_at": now,
        "error": error,
    }
    if record.checkpoint < len(record.steps):
        step = record.steps[record.checkpoint]
        if step.status is WorkflowStepStatus.RUNNING:
            failed = WorkflowStepRecord(
                name=step.name,
                status=WorkflowStepStatus.FAILED,
                attempts=step.attempts,
                error=error,
            )
            updates["steps"] = _replace_step(record, failed)
    return updates


def _cancel_fields[ContextT: BaseModel, ResultT: BaseModel](
    record: WorkflowInstance[ContextT, ResultT], now: datetime
) -> tuple[dict[str, object], WorkflowEventKind]:
    if record.status is WorkflowStatus.CANCELLED or record.cancellation_requested:
        return {}, "cancel_requested"
    _require(
        record.status in {WorkflowStatus.PENDING, WorkflowStatus.RUNNING},
        "Only pending/running workflows can be cancelled",
    )
    updates: dict[str, object] = {"cancellation_requested": True}
    if record.status is WorkflowStatus.PENDING:
        updates.update(status=WorkflowStatus.CANCELLED, finished_at=now)
    return (
        updates,
        "cancelled" if record.status is WorkflowStatus.PENDING else "cancel_requested",
    )
