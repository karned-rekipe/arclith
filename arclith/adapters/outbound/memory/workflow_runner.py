"""Local reference execution adapter; pair with an explicitly injected store."""

from pydantic import BaseModel

from arclith.application.services.workflow_runner import SequentialWorkflowRunner


class InMemoryWorkflowRunner[ContextT: BaseModel, ResultT: BaseModel](
    SequentialWorkflowRunner[ContextT, ResultT]
):
    """Await run/resume directly on one event loop; no durable scheduler/recovery.

    This adapter uses the provider-neutral sequential algorithm. Its caller owns
    all tasks and must collect cancellation/errors. No step SDK is constructed.
    """
