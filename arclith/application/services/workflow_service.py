"""Typed application operations for one workflow definition."""

from pydantic import BaseModel

from arclith.domain.errors.workflow import (
    WorkflowDefinitionConflict,
    WorkflowNotFound,
    WorkflowResultUnavailable,
    WorkflowVersionConflict,
)
from arclith.domain.models.workflow import (
    WorkflowDefinition,
    WorkflowId,
    WorkflowInstance,
    WorkflowStatus,
)
from arclith.domain.ports.outbound.workflow_runner import WorkflowRunnerPort
from arclith.domain.ports.outbound.workflow_store import WorkflowStorePort
from arclith.domain.services.workflow_lifecycle import CancelWorkflow


class WorkflowService[ContextT: BaseModel, ResultT: BaseModel]:
    def __init__(
        self,
        definition: WorkflowDefinition,
        runner: WorkflowRunnerPort[ContextT, ResultT],
        store: WorkflowStorePort[ContextT, ResultT],
    ) -> None:
        self.definition = WorkflowDefinition.model_validate(definition)
        self._runner = runner
        self._store = store

    async def start(
        self, context: ContextT, *, idempotency_key: str | None = None
    ) -> WorkflowId:
        return (
            await self._store.create(
                self.definition, context, idempotency_key=idempotency_key
            )
        ).workflow_id

    async def get_status(
        self, workflow_id: WorkflowId
    ) -> WorkflowInstance[ContextT, ResultT]:
        record = await self._store.get(workflow_id)
        if record is None:
            raise WorkflowNotFound("Workflow not found")
        if record.definition != self.definition:
            raise WorkflowDefinitionConflict(
                "Workflow belongs to a different definition"
            )
        return record

    async def cancel(
        self, workflow_id: WorkflowId
    ) -> WorkflowInstance[ContextT, ResultT]:
        for _ in range(8):
            record = await self.get_status(workflow_id)
            try:
                return await self._store.change(
                    workflow_id, CancelWorkflow(), expected_version=record.version
                )
            except WorkflowVersionConflict:
                continue
        raise WorkflowVersionConflict("Workflow changed repeatedly; retry cancellation")

    async def resume(
        self, workflow_id: WorkflowId
    ) -> WorkflowInstance[ContextT, ResultT]:
        await self.get_status(workflow_id)
        return await self._runner.resume(workflow_id)

    async def get_result(self, workflow_id: WorkflowId) -> ResultT:
        record = await self.get_status(workflow_id)
        if record.status is not WorkflowStatus.COMPLETED or record.result is None:
            raise WorkflowResultUnavailable("Workflow has not completed")
        return record.result
