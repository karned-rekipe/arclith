from abc import ABC, abstractmethod
from dataclasses import dataclass

from pydantic import BaseModel

from arclith.domain.models.workflow import WorkflowId, WorkflowInstance
from arclith.domain.ports.outbound.job_runner import CancellationToken


@dataclass(frozen=True)
class StepExecutionContext:
    workflow_id: WorkflowId
    step_name: str
    execution_key: str
    attempt: int
    cancellation: CancellationToken


class WorkflowStep[ContextT: BaseModel](ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Stable public name, matching the versioned definition."""

    @abstractmethod
    async def execute(
        self, context: ContextT, *, execution: StepExecutionContext
    ) -> ContextT:
        """Return a validated context. Unconfirmed effects can be replayed.

        Use execution_key for durable external idempotence; it stays identical
        across attempts. Cancellation is cooperative, not remote rollback.
        """


class WorkflowResultMapper[ContextT: BaseModel, ResultT: BaseModel](ABC):
    @abstractmethod
    def build_result(self, context: ContextT) -> ResultT:
        """Pure deterministic projection; may be repeated, without business effects."""


class WorkflowRunnerPort[ContextT: BaseModel, ResultT: BaseModel](ABC):
    @abstractmethod
    async def run(self, workflow_id: WorkflowId) -> WorkflowInstance[ContextT, ResultT]:
        """Execute pending work; the caller owns and awaits this execution."""

    @abstractmethod
    async def resume(
        self, workflow_id: WorkflowId
    ) -> WorkflowInstance[ContextT, ResultT]:
        """Resume failed/unconfirmed work within the persisted step budget."""
