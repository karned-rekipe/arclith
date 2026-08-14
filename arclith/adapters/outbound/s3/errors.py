from collections.abc import Mapping
from typing import NoReturn

from arclith.domain.ports.outbound.file_storage import (
    FileStorageConflict,
    FileStorageError,
    FileStorageNotFound,
    FileStoragePermissionDenied,
    FileStorageUnavailable,
)

_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound", "Not Found"})
_PERMISSION_CODES = frozenset(
    {
        "403",
        "AccessDenied",
        "AllAccessDisabled",
        "ExpiredToken",
        "InvalidAccessKeyId",
        "InvalidToken",
        "SignatureDoesNotMatch",
    }
)
_PERMISSION_ERROR_NAMES = frozenset(
    {
        "CredentialRetrievalError",
        "NoCredentialsError",
        "PartialCredentialsError",
        "ProfileNotFound",
        "SSOTokenLoadError",
        "UnauthorizedSSOTokenError",
    }
)
_CONFLICT_CODES = frozenset(
    {
        "ConditionalRequestConflict",
        "OperationAborted",
        "PreconditionFailed",
    }
)
_UNAVAILABLE_CODES = frozenset(
    {
        "InternalError",
        "NoSuchBucket",
        "RequestTimeout",
        "ServiceUnavailable",
        "SlowDown",
        "Throttling",
        "ThrottlingException",
    }
)
_UNAVAILABLE_ERROR_NAMES = frozenset(
    {
        "ConnectTimeoutError",
        "ConnectionClosedError",
        "EndpointConnectionError",
        "ReadTimeoutError",
    }
)


def is_not_found_error(error: Exception) -> bool:
    return provider_error_code(error) in _NOT_FOUND_CODES


def provider_error_code(error: Exception) -> str | None:
    response = getattr(error, "response", None)
    if not isinstance(response, Mapping):
        return None
    error_payload = response.get("Error")
    if not isinstance(error_payload, Mapping):
        return None
    code = error_payload.get("Code")
    if code is None:
        return None
    return str(code)


def s3_storage_error_from_provider(error: Exception, *, key: str) -> FileStorageError:
    code = provider_error_code(error)
    error_name = type(error).__name__
    if code in _NOT_FOUND_CODES:
        return FileStorageNotFound("s3 storage object not found", key=key)
    if code in _PERMISSION_CODES or error_name in _PERMISSION_ERROR_NAMES:
        return FileStoragePermissionDenied(
            "s3 storage operation is not permitted", key=key
        )
    if code in _CONFLICT_CODES:
        return FileStorageConflict(
            "s3 storage operation conflicted with backend state",
            key=key,
        )
    if code in _UNAVAILABLE_CODES or error_name in _UNAVAILABLE_ERROR_NAMES:
        return FileStorageUnavailable("s3 storage backend is unavailable", key=key)
    return FileStorageUnavailable("s3 storage operation failed", key=key)


def raise_s3_storage_error(error: Exception, *, key: str) -> NoReturn:
    raise s3_storage_error_from_provider(error, key=key) from error
