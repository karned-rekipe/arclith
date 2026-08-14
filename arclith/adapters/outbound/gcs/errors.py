from typing import NoReturn

from arclith.domain.ports.outbound.file_storage import (
    FileStorageConflict,
    FileStorageError,
    FileStorageNotFound,
    FileStoragePermissionDenied,
    FileStorageUnavailable,
)

_NOT_FOUND_CODES = frozenset({"404"})
_NOT_FOUND_ERROR_NAMES = frozenset({"NotFound"})
_PERMISSION_CODES = frozenset({"401", "403"})
_PERMISSION_ERROR_NAMES = frozenset(
    {
        "DefaultCredentialsError",
        "Forbidden",
        "GoogleAuthError",
        "PermissionDenied",
        "RefreshError",
        "Unauthenticated",
        "Unauthorized",
    }
)
_CONFLICT_CODES = frozenset({"409", "412"})
_CONFLICT_ERROR_NAMES = frozenset(
    {
        "Aborted",
        "Conflict",
        "DataCorruption",
        "PreconditionFailed",
    }
)
_UNAVAILABLE_CODES = frozenset({"408", "429", "500", "502", "503", "504"})
_UNAVAILABLE_ERROR_NAMES = frozenset(
    {
        "BadGateway",
        "DeadlineExceeded",
        "GatewayTimeout",
        "InternalServerError",
        "RetryError",
        "ServiceUnavailable",
        "TooManyRequests",
        "TransportError",
    }
)


def is_not_found_error(error: Exception) -> bool:
    return (
        provider_error_code(error) in _NOT_FOUND_CODES
        or type(error).__name__ in _NOT_FOUND_ERROR_NAMES
    )


def provider_error_code(error: Exception) -> str | None:
    code = getattr(error, "code", None)
    if code is not None:
        return str(code)

    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code is not None:
        return str(status_code)
    status = getattr(response, "status", None)
    if status is not None:
        return str(status)

    return None


def gcs_storage_error_from_provider(error: Exception, *, key: str) -> FileStorageError:
    code = provider_error_code(error)
    error_name = type(error).__name__
    if code in _NOT_FOUND_CODES or error_name in _NOT_FOUND_ERROR_NAMES:
        return FileStorageNotFound("gcs storage object not found", key=key)
    if code in _PERMISSION_CODES or error_name in _PERMISSION_ERROR_NAMES:
        return FileStoragePermissionDenied(
            "gcs storage operation is not permitted", key=key
        )
    if code in _CONFLICT_CODES or error_name in _CONFLICT_ERROR_NAMES:
        return FileStorageConflict(
            "gcs storage operation conflicted with backend state",
            key=key,
        )
    if code in _UNAVAILABLE_CODES or error_name in _UNAVAILABLE_ERROR_NAMES:
        return FileStorageUnavailable("gcs storage backend is unavailable", key=key)
    return FileStorageUnavailable("gcs storage operation failed", key=key)


def raise_gcs_storage_error(error: Exception, *, key: str) -> NoReturn:
    raise gcs_storage_error_from_provider(error, key=key) from error
