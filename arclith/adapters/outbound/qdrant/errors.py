from __future__ import annotations

from collections.abc import Mapping

from arclith.domain.ports.outbound.vector_store import (
    VectorStoreCollectionNotFound,
    VectorStoreError,
    VectorStorePermissionDenied,
    VectorStoreUnavailable,
)

_PERMISSION_CODES = frozenset({401, 403})
_NOT_FOUND_CODES = frozenset({404})
_UNAVAILABLE_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_UNAVAILABLE_ERROR_NAMES = frozenset(
    {
        "ConnectError",
        "ConnectTimeout",
        "PoolTimeout",
        "ReadError",
        "ReadTimeout",
        "ResponseHandlingException",
        "WriteError",
        "WriteTimeout",
    }
)


def qdrant_error_from_provider(error: Exception) -> VectorStoreError:
    status_code = _provider_status_code(error)
    if status_code in _PERMISSION_CODES:
        return VectorStorePermissionDenied(
            "qdrant vector-store operation is not permitted"
        )
    if status_code in _NOT_FOUND_CODES:
        return VectorStoreCollectionNotFound(
            "qdrant vector-store collection was not found"
        )
    if (
        status_code in _UNAVAILABLE_CODES
        or type(error).__name__ in _UNAVAILABLE_ERROR_NAMES
    ):
        return VectorStoreUnavailable("qdrant vector-store is unavailable")
    return VectorStoreUnavailable("qdrant vector-store operation failed")


def _provider_status_code(error: Exception) -> int | None:
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(error, "response", None)
    if isinstance(response, Mapping):
        response_status = response.get("status_code") or response.get("status")
    else:
        response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None
