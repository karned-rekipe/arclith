from abc import ABC, abstractmethod
from uuid import UUID

from pydantic import BaseModel

from arclith.domain.models.workflow import (
    WorkflowDefinition,
    WorkflowId,
    WorkflowInstance,
)
from arclith.domain.services.workflow_lifecycle import WorkflowChange


class WorkflowStorePort[ContextT: BaseModel, ResultT: BaseModel](ABC):
    """Atomic versioned transitions and exclusive execution per instance.

    Scope one store to one definition/schema pair. Snapshots are isolated.
    A claim has no implicit expiry: durable adapters must fence previous owners
    including their external effects before recovery. Never steal a live claim.
    Checkpoint context and step success are one atomic commit.
    """

    @abstractmethod
    async def create(
        self,
        definition: WorkflowDefinition,
        context: ContextT,
        *,
        idempotency_key: str | None = None,
    ) -> WorkflowInstance[ContextT, ResultT]:
        """Persist definition/schema fingerprint and bounded input before execution."""

    @abstractmethod
    async def get(
        self, workflow_id: WorkflowId
    ) -> WorkflowInstance[ContextT, ResultT] | None:
        """Read a detached snapshot."""

    @abstractmethod
    async def claim(self, workflow_id: WorkflowId, owner: UUID) -> None:
        """Atomically reserve exclusive execution; reject a concurrent owner."""

    @abstractmethod
    async def release(self, workflow_id: WorkflowId, owner: UUID) -> None:
        """Release only the matching owner's claim, after it stops executing."""

    @abstractmethod
    async def change(
        self,
        workflow_id: WorkflowId,
        change: WorkflowChange[ContextT, ResultT],
        *,
        expected_version: int,
        owner: UUID | None = None,
    ) -> WorkflowInstance[ContextT, ResultT]:
        """Apply a validated transition under CAS and owner checks.

        Only CancelWorkflow is permitted without an execution claim.
        Payloads obey the shared Job JSON contract: 64 KiB, 32 levels, no SDK
        objects or hidden secrets. Reject invalid data before storing effects.
        """
