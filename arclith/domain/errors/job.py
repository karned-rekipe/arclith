"""Public, payload-free failures of the job execution contract."""


class JobOperationError(Exception):
    """Base error for job operations."""


class JobNotFound(JobOperationError):
    """The requested identity is unknown in this store."""


class JobTransitionError(JobOperationError):
    """The operation is incompatible with the current lifecycle."""


class JobVersionConflict(JobOperationError):
    """Another operation changed the record since it was read."""


class JobIdempotencyConflict(JobOperationError):
    """The submission key already identifies a different request."""


class JobResultUnavailable(JobOperationError):
    """A result is only available after successful execution."""


class JobCancellationRequested(JobOperationError):
    """A cooperative handler acknowledged a cancellation request."""
