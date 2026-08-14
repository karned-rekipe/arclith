from typing import NoReturn

from arclith.domain.ports.outbound.file_storage import (
    FileStorageConflict,
    FileStorageError,
    FileStorageNotFound,
    FileStoragePermissionDenied,
    FileStorageUnavailable,
)

_NOT_FOUND_CODES = frozenset(
    {
        "404",
        "BlobNotFound",
        "ContainerNotFound",
        "ResourceNotFound",
    }
)
_NOT_FOUND_ERROR_NAMES = frozenset({"ResourceNotFoundError"})

_PERMISSION_CODES = frozenset(
    {
        "401",
        "403",
        "AccountIsDisabled",
        "AuthenticationFailed",
        "AuthorizationFailure",
        "AuthorizationPermissionMismatch",
        "InvalidAuthenticationInfo",
        "NoAuthenticationInformation",
    }
)
_PERMISSION_ERROR_NAMES = frozenset({"ClientAuthenticationError"})

_CONFLICT_CODES = frozenset(
    {
        "409",
        "412",
        "BlobAlreadyExists",
        "ConditionNotMet",
        "ContainerAlreadyExists",
        "LeaseAlreadyPresent",
        "LeaseIdMissing",
    }
)
_CONFLICT_ERROR_NAMES = frozenset({"ResourceExistsError", "ResourceModifiedError"})

_UNAVAILABLE_CODES = frozenset(
    {
        "408",
        "429",
        "500",
        "502",
        "503",
        "504",
        "InternalError",
        "OperationTimedOut",
        "ServerBusy",
    }
)
_UNAVAILABLE_ERROR_NAMES = frozenset(
    {
        "ServiceRequestError",
        "ServiceRequestTimeoutError",
        "ServiceResponseError",
    }
)


def is_not_found_error(error: Exception) -> bool:
    return (
        provider_error_code(error) in _NOT_FOUND_CODES
        or type(error).__name__ in _NOT_FOUND_ERROR_NAMES
    )


def provider_error_code(error: Exception) -> str | None:
    error_code = getattr(error, "error_code", None)
    if error_code is not None:
        return str(error_code)

    status_code = getattr(error, "status_code", None)
    if status_code is not None:
        return str(status_code)

    response = getattr(error, "response", None)
    response_status_code = getattr(response, "status_code", None)
    if response_status_code is not None:
        return str(response_status_code)
    response_status = getattr(response, "status", None)
    if response_status is not None:
        return str(response_status)

    return None


def azure_blob_storage_error_from_provider(
    error: Exception,
    *,
    key: str,
) -> FileStorageError:
    code = provider_error_code(error)
    error_name = type(error).__name__
    if code in _NOT_FOUND_CODES or error_name in _NOT_FOUND_ERROR_NAMES:
        return FileStorageNotFound("azure blob storage object not found", key=key)
    if code in _PERMISSION_CODES or error_name in _PERMISSION_ERROR_NAMES:
        return FileStoragePermissionDenied(
            "azure blob storage operation is not permitted", key=key
        )
    if code in _CONFLICT_CODES or error_name in _CONFLICT_ERROR_NAMES:
        return FileStorageConflict(
            "azure blob storage operation conflicted with backend state",
            key=key,
        )
    if code in _UNAVAILABLE_CODES or error_name in _UNAVAILABLE_ERROR_NAMES:
        return FileStorageUnavailable(
            "azure blob storage backend is unavailable", key=key
        )
    return FileStorageUnavailable("azure blob storage operation failed", key=key)


def raise_azure_blob_storage_error(error: Exception, *, key: str) -> NoReturn:
    raise azure_blob_storage_error_from_provider(error, key=key) from error
