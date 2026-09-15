"""Public workflow failures never contain business payloads or exception text."""


class WorkflowError(Exception):
    pass


class WorkflowNotFound(WorkflowError):
    pass


class WorkflowBusy(WorkflowError):
    pass


class WorkflowVersionConflict(WorkflowError):
    pass


class WorkflowDefinitionConflict(WorkflowError):
    pass


class WorkflowTransitionError(WorkflowError):
    pass


class WorkflowIdempotencyConflict(WorkflowError):
    pass


class WorkflowResultUnavailable(WorkflowError):
    pass
