"""Bounded, non-durable reference store on one asyncio event loop."""

import asyncio
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel

from arclith.domain.errors.workflow import (
    WorkflowBusy,
    WorkflowIdempotencyConflict,
    WorkflowNotFound,
    WorkflowTransitionError,
    WorkflowVersionConflict,
)
from arclith.domain.models.job import JobRequest
from arclith.domain.models.workflow import (
    WorkflowDefinition,
    WorkflowId,
    WorkflowInstance,
    WorkflowStatus,
    WorkflowStepRecord,
)
from arclith.domain.ports.outbound.workflow_store import WorkflowStorePort
from arclith.domain.services.job_payload import payload_json, snapshot_payload
from arclith.domain.services.workflow_definition import workflow_definition_digest
from arclith.domain.services.workflow_lifecycle import (
    CancelWorkflow,
    CommitWorkflowStep,
    CompleteWorkflow,
    WorkflowChange,
    transition_workflow,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InMemoryWorkflowStore[ContextT: BaseModel, ResultT: BaseModel](
    WorkflowStorePort[ContextT, ResultT]
):
    def __init__(
        self,
        context_type: type[ContextT],
        result_type: type[ResultT],
        *,
        max_instances: int = 1000,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if type(max_instances) is not int or max_instances < 1:
            raise ValueError("max_instances must be a positive integer")
        self._context_type = context_type
        self._result_type = result_type
        self._max_instances = max_instances
        self._clock = clock
        self._records: dict[WorkflowId, WorkflowInstance[ContextT, ResultT]] = {}
        self._owners: dict[WorkflowId, UUID] = {}
        self._keys: dict[str, tuple[str, WorkflowId]] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        definition: WorkflowDefinition,
        context: ContextT,
        *,
        idempotency_key: str | None = None,
    ) -> WorkflowInstance[ContextT, ResultT]:
        definition = WorkflowDefinition.model_validate(definition)
        context = snapshot_payload(context, self._context_type)
        digest = workflow_definition_digest(
            definition, self._context_type, self._result_type
        )
        # Reuse Job's public idempotency-key validation, without a second policy.
        key = JobRequest(
            payload=context, idempotency_key=idempotency_key
        ).idempotency_key
        fingerprint = hashlib.sha256(
            (digest + payload_json(context)).encode()
        ).hexdigest()
        async with self._lock:
            if key is not None and key in self._keys:
                previous, workflow_id = self._keys[key]
                if previous != fingerprint:
                    raise WorkflowIdempotencyConflict(
                        "Key belongs to another workflow input/definition"
                    )
                return self._records[workflow_id].model_copy(deep=True)
            if len(self._records) >= self._max_instances:
                raise WorkflowTransitionError("Workflow store capacity reached")
            now = self._clock()
            record = WorkflowInstance[ContextT, ResultT](
                definition=definition,
                definition_digest=digest,
                context=context,
                steps=tuple(
                    WorkflowStepRecord(name=step.name) for step in definition.steps
                ),
                created_at=now,
                updated_at=now,
            )
            self._records[record.workflow_id] = record.model_copy(deep=True)
            if key is not None:
                self._keys[key] = (fingerprint, record.workflow_id)
            return record.model_copy(deep=True)

    async def get(
        self, workflow_id: WorkflowId
    ) -> WorkflowInstance[ContextT, ResultT] | None:
        async with self._lock:
            record = self._records.get(workflow_id)
            return record.model_copy(deep=True) if record is not None else None

    def _get(self, workflow_id: WorkflowId) -> WorkflowInstance[ContextT, ResultT]:
        record = self._records.get(workflow_id)
        if record is None:
            raise WorkflowNotFound("Workflow not found")
        return record

    async def claim(self, workflow_id: WorkflowId, owner: UUID) -> None:
        async with self._lock:
            self._get(workflow_id)
            if workflow_id in self._owners:
                raise WorkflowBusy("Workflow already has an execution owner")
            self._owners[workflow_id] = owner

    async def release(self, workflow_id: WorkflowId, owner: UUID) -> None:
        async with self._lock:
            if self._owners.get(workflow_id) != owner:
                raise WorkflowBusy("Workflow claim belongs to another owner")
            del self._owners[workflow_id]

    async def change(
        self,
        workflow_id: WorkflowId,
        change: WorkflowChange[ContextT, ResultT],
        *,
        expected_version: int,
        owner: UUID | None = None,
    ) -> WorkflowInstance[ContextT, ResultT]:
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("expected_version must be a positive integer")
        async with self._lock:
            record = self._get(workflow_id)
            if not isinstance(change, CancelWorkflow) and (
                owner is None or self._owners.get(workflow_id) != owner
            ):
                raise WorkflowBusy("An active execution claim is required")
            if expected_version != record.version:
                raise WorkflowVersionConflict("Workflow version changed")
            if isinstance(change, CommitWorkflowStep):
                change = CommitWorkflowStep(
                    snapshot_payload(change.context, self._context_type)
                )
            if isinstance(change, CompleteWorkflow):
                change = CompleteWorkflow(
                    snapshot_payload(change.result, self._result_type)
                )
            updated = transition_workflow(record, change, now=self._clock())
            self._records[workflow_id] = updated.model_copy(deep=True)
            return updated.model_copy(deep=True)

    async def delete_terminal(self, workflow_id: WorkflowId) -> None:
        """Explicit retention; deletion also releases submission-key deduplication."""
        async with self._lock:
            record = self._get(workflow_id)
            if workflow_id in self._owners or record.status not in {
                WorkflowStatus.COMPLETED,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELLED,
            }:
                raise WorkflowTransitionError(
                    "Only unclaimed terminal workflows may be deleted"
                )
            del self._records[workflow_id]
            self._keys = {
                key: entry
                for key, entry in self._keys.items()
                if entry[1] != workflow_id
            }
