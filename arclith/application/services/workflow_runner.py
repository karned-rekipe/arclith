"""Deterministic sequential runner with caller-owned execution and explicit resume."""

import asyncio
from collections.abc import Sequence
from uuid import UUID, uuid4

from pydantic import BaseModel

from arclith.domain.errors.job import JobCancellationRequested
from arclith.domain.errors.workflow import (
    WorkflowDefinitionConflict,
    WorkflowNotFound,
    WorkflowVersionConflict,
)
from arclith.domain.models.workflow import (
    WorkflowDefinition,
    WorkflowFailure,
    WorkflowId,
    WorkflowInstance,
    WorkflowStatus,
)
from arclith.domain.ports.outbound.job_runner import CancellationToken
from arclith.domain.ports.outbound.workflow_runner import (
    StepExecutionContext,
    WorkflowResultMapper,
    WorkflowRunnerPort,
    WorkflowStep,
)
from arclith.domain.ports.outbound.workflow_store import WorkflowStorePort
from arclith.domain.services.job_payload import snapshot_payload
from arclith.domain.services.workflow_definition import workflow_definition_digest
from arclith.domain.services.workflow_lifecycle import (
    AcknowledgeWorkflowCancellation,
    BeginWorkflowStep,
    CommitWorkflowStep,
    CompleteWorkflow,
    FailWorkflow,
    StartWorkflow,
    WorkflowChange,
)


class _WorkflowCancellation[ContextT: BaseModel, ResultT: BaseModel](CancellationToken):
    def __init__(
        self, store: WorkflowStorePort[ContextT, ResultT], workflow_id: WorkflowId
    ) -> None:
        self._store = store
        self._workflow_id = workflow_id

    async def is_requested(self) -> bool:
        record = await self._store.get(self._workflow_id)
        if record is None:
            raise WorkflowNotFound("Workflow not found")
        return record.cancellation_requested


class SequentialWorkflowRunner[ContextT: BaseModel, ResultT: BaseModel](
    WorkflowRunnerPort[ContextT, ResultT]
):
    """Executes one pass, stopping on failure. Resume consumes another step attempt.

    A persistence error propagates with an uncertain outcome; inspect stored
    checkpoints before resume. No background task, automatic retry or lease.
    """

    def __init__(
        self,
        definition: WorkflowDefinition,
        store: WorkflowStorePort[ContextT, ResultT],
        steps: Sequence[WorkflowStep[ContextT]],
        result_mapper: WorkflowResultMapper[ContextT, ResultT],
        *,
        context_type: type[ContextT],
        result_type: type[ResultT],
    ) -> None:
        self.definition = WorkflowDefinition.model_validate(definition)
        self._digest = workflow_definition_digest(
            self.definition, context_type, result_type
        )
        self._store = store
        self._steps = tuple(steps)
        self._result_mapper = result_mapper
        self._context_type = context_type
        self._result_type = result_type
        if tuple(step.name for step in self._steps) != tuple(
            step.name for step in self.definition.steps
        ):
            raise ValueError("Injected steps must exactly match definition order/names")

    async def _get(
        self, workflow_id: WorkflowId
    ) -> WorkflowInstance[ContextT, ResultT]:
        record = await self._store.get(workflow_id)
        if record is None:
            raise WorkflowNotFound("Workflow not found")
        if (
            record.definition_digest != self._digest
            or record.definition != self.definition
        ):
            raise WorkflowDefinitionConflict(
                "Workflow definition/schema differs from its stored version"
            )
        return record

    async def _change(
        self,
        workflow_id: WorkflowId,
        owner: UUID,
        change: WorkflowChange[ContextT, ResultT],
    ) -> WorkflowInstance[ContextT, ResultT]:
        for _ in range(8):
            record = await self._get(workflow_id)
            # A cancellation racing BeginStep must prevent the business call.
            effective = (
                AcknowledgeWorkflowCancellation()
                if isinstance(change, BeginWorkflowStep)
                and record.cancellation_requested
                else change
            )
            try:
                return await self._store.change(
                    workflow_id, effective, expected_version=record.version, owner=owner
                )
            except WorkflowVersionConflict:
                continue
        raise WorkflowVersionConflict(
            "Workflow changed repeatedly; inspect state before retry"
        )

    async def run(self, workflow_id: WorkflowId) -> WorkflowInstance[ContextT, ResultT]:
        return await self._execute(workflow_id, resume=False)

    async def resume(
        self, workflow_id: WorkflowId
    ) -> WorkflowInstance[ContextT, ResultT]:
        return await self._execute(workflow_id, resume=True)

    async def _execute(
        self, workflow_id: WorkflowId, *, resume: bool
    ) -> WorkflowInstance[ContextT, ResultT]:
        await self._get(workflow_id)
        owner = uuid4()
        await self._store.claim(workflow_id, owner)
        try:
            record = await self._change(
                workflow_id, owner, StartWorkflow(resume=resume)
            )
            try:
                return await self._drive(record, owner)
            except asyncio.CancelledError:
                latest = await self._get(workflow_id)
                if latest.status is WorkflowStatus.RUNNING:
                    await self._change(
                        workflow_id,
                        owner,
                        FailWorkflow(WorkflowFailure(code="execution_interrupted")),
                    )
                raise
        finally:
            await self._store.release(workflow_id, owner)

    async def _drive(
        self, record: WorkflowInstance[ContextT, ResultT], owner: UUID
    ) -> WorkflowInstance[ContextT, ResultT]:
        workflow_id = record.workflow_id
        cancellation = _WorkflowCancellation(self._store, workflow_id)
        while record.checkpoint < len(self._steps):
            if await cancellation.is_requested():
                return await self._change(
                    workflow_id, owner, AcknowledgeWorkflowCancellation()
                )
            record = await self._change(workflow_id, owner, BeginWorkflowStep())
            if record.status is WorkflowStatus.CANCELLED:
                return record
            record = await self._step(record, owner, cancellation)
            if record.status is not WorkflowStatus.RUNNING:
                return record
        if await cancellation.is_requested():
            return await self._change(
                workflow_id, owner, AcknowledgeWorkflowCancellation()
            )
        try:
            result = snapshot_payload(
                self._result_mapper.build_result(
                    snapshot_payload(record.context, self._context_type)
                ),
                self._result_type,
            )
        except Exception:
            return await self._change(
                workflow_id, owner, FailWorkflow(WorkflowFailure(code="result_failed"))
            )
        # Publication is outside the business boundary: failures are uncertain.
        return await self._change(workflow_id, owner, CompleteWorkflow(result))

    async def _step(
        self,
        record: WorkflowInstance[ContextT, ResultT],
        owner: UUID,
        cancellation: CancellationToken,
    ) -> WorkflowInstance[ContextT, ResultT]:
        current = record.steps[record.checkpoint]
        execution = StepExecutionContext(
            workflow_id=record.workflow_id,
            step_name=current.name,
            attempt=current.attempts,
            execution_key=f"{record.workflow_id}:{self._digest}:{current.name}",
            cancellation=cancellation,
        )
        try:
            context = await self._steps[record.checkpoint].execute(
                snapshot_payload(record.context, self._context_type),
                execution=execution,
            )
            context = snapshot_payload(context, self._context_type)
        except JobCancellationRequested:
            if await cancellation.is_requested():
                return await self._change(
                    record.workflow_id, owner, AcknowledgeWorkflowCancellation()
                )
            return await self._fail_step(record.workflow_id, owner, "step_failed")
        except NotImplementedError:
            return await self._fail_step(
                record.workflow_id, owner, "step_not_implemented"
            )
        except Exception:
            return await self._fail_step(record.workflow_id, owner, "step_failed")
        # Checkpoint and success are atomic. Never classify storage errors as
        # step failures: a response may be lost after a successful commit.
        return await self._change(
            record.workflow_id, owner, CommitWorkflowStep(context)
        )

    async def _fail_step(
        self, workflow_id: WorkflowId, owner: UUID, code: str
    ) -> WorkflowInstance[ContextT, ResultT]:
        return await self._change(
            workflow_id,
            owner,
            FailWorkflow(WorkflowFailure.model_validate({"code": code})),
        )
