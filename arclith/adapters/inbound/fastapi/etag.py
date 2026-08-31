"""ETag and conditional request middleware for optimistic locking.

Implements HTTP-level concurrency control via ETag/If-Match headers.
Prevents lost updates in distributed systems without payload version fields.

RFC References:
    - RFC 7232: Conditional Requests
    - RFC 9110: HTTP Semantics (ETag, If-Match, If-None-Match)

Usage:
    app.add_middleware(ETaggerMiddleware, logger=logger)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from arclith.domain.ports.outbound.logger import Logger


class ETaggerMiddleware:
    """ASGI middleware that manages ETags for entity versioning and conditional requests.

    Workflow (GET):
        1. Handler returns entity with `version` field
        2. Middleware generates ETag: `"v{version}"` (e.g., "v1", "v42")
        3. Response includes `ETag: "v1"` header

    Workflow (PUT/PATCH):
        1. Client sends `If-Match: "v1"` header
        2. Middleware extracts expected version
        3. Handler receives expected version in request state
        4. Service validates version and rejects stale mutations
        5. Mutations keep their original response headers

    Workflow (conditional GET - cache validation):
        1. Client sends `If-None-Match: "v1"` header
        2. Middleware extracts current version from response
        3. If match → 304 Not Modified (no body)
        4. If different → 200 OK with new ETag

    Benefits:
        - No version field in PUT/PATCH payloads (cleaner API)
        - Standard HTTP semantics (CDN/proxy compatible)
        - Application-level validation can reject version conflicts
        - 304 Not Modified for cache validation
    """

    def __init__(self, app: Any, logger: "Logger") -> None:
        self._app = app
        self._logger = logger

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        method = scope.get("method", "")
        headers_dict = {
            k.decode().lower(): v.decode() for k, v in scope.get("headers", [])
        }

        # Initialize state for conditional requests
        if "state" not in scope:
            scope["state"] = {}

        # Handle If-Match for PUT/PATCH (require exact version)
        if method in {"PUT", "PATCH"}:
            if_match = headers_dict.get("if-match")
            if if_match:
                # Strip quotes and "v" prefix: "v1" → 1
                expected_version = self._parse_etag(if_match)
                scope["state"]["expected_version"] = expected_version
                self._logger.debug(
                    "🔍 Conditional update",
                    method=method,
                    if_match=if_match,
                    expected_version=expected_version,
                )

        # Handle If-None-Match for GET (cache validation)
        if_none_match = headers_dict.get("if-none-match")
        if if_none_match:
            scope["state"]["if_none_match"] = if_none_match

        response_data: dict[str, Any] = {"status": 200, "headers": [], "body": b""}

        async def _send_wrapper(message: Any) -> None:
            if message["type"] == "http.response.start":
                response_data["status"] = message["status"]
                response_data["headers"] = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                response_data["body"] += message.get("body", b"")

        await self._app(scope, receive, _send_wrapper)
        await self._send_response(send, method, if_none_match, response_data)

    async def _send_response(
        self,
        send: Any,
        method: str,
        if_none_match: str | None,
        response_data: dict[str, Any],
    ) -> None:
        etag = self._extract_etag_from_body(
            response_data["body"], response_data["status"]
        )
        if method != "GET" or etag is None:
            await self._send_original_response(send, response_data)
            return

        if if_none_match and self._etag_matches(if_none_match, etag):
            self._logger.info(
                "💾 Cache hit (304 Not Modified)",
                if_none_match=if_none_match,
                etag=etag,
            )
            await send(
                {
                    "type": "http.response.start",
                    "status": 304,
                    "headers": self._headers_with_etag(
                        response_data["headers"], etag, drop_body_headers=True
                    ),
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        await send(
            {
                "type": "http.response.start",
                "status": response_data["status"],
                "headers": self._headers_with_etag(response_data["headers"], etag),
            }
        )
        await send({"type": "http.response.body", "body": response_data["body"]})

    @staticmethod
    async def _send_original_response(send: Any, response_data: dict[str, Any]) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": response_data["status"],
                "headers": response_data["headers"],
            }
        )
        await send({"type": "http.response.body", "body": response_data["body"]})

    @staticmethod
    def _headers_with_etag(
        headers: list[tuple[bytes, bytes]],
        etag: str,
        *,
        drop_body_headers: bool = False,
    ) -> list[tuple[bytes, bytes]]:
        dropped = {b"etag"}
        if drop_body_headers:
            dropped.update({b"content-length"})
        filtered = [
            (key, value) for key, value in headers if key.lower() not in dropped
        ]
        return [*filtered, (b"etag", etag.encode("utf-8"))]

    @staticmethod
    def _etag_matches(if_none_match: str, etag: str) -> bool:
        candidates = [candidate.strip() for candidate in if_none_match.split(",")]
        normalized_etag = etag.strip('"')
        return any(candidate.strip('"') == normalized_etag for candidate in candidates)

    def _parse_etag(self, etag: str) -> int | None:
        """Parse ETag header to extract version number.

        Examples:
            "v1" → 1
            "v42" → 42
            W/"v1" → 1 (weak etag)
        """
        etag = etag.strip()
        # Remove W/ prefix for weak ETags
        etag = etag.removeprefix("W/")
        # Remove quotes
        etag = etag.strip('"')
        # Remove v prefix
        etag = etag.removeprefix("v")

        try:
            return int(etag)
        except ValueError:
            self._logger.warning("⚠️ Invalid ETag format", etag=etag)
            return None

    def _extract_etag_from_body(self, body: bytes, status: int) -> str | None:
        """Extract version from JSON response body to generate ETag.

        Only for successful responses (2xx) with JSON body containing 'version' field.
        """
        if not (200 <= status < 300):
            return None

        if not body:
            return None

        try:
            data = json.loads(body)

            # Check for version in data.data.version (wrapped response)
            if isinstance(data, dict):
                if "data" in data and isinstance(data["data"], dict):
                    version = data["data"].get("version")
                    if version is not None:
                        return f'"v{version}"'

                # Check for version in data.version (direct response)
                version = data.get("version")
                if version is not None:
                    return f'"v{version}"'

            return None
        except (json.JSONDecodeError, KeyError, TypeError):
            return None


def get_expected_version_from_request(request: Any) -> int | None:
    """FastAPI dependency to extract expected version from If-Match header.

    Usage:
        async def update_resource(
            expected_version: Annotated[int | None, Depends(get_expected_version_from_request)]
        ):
            if expected_version:
                # Validate against entity.version
                ...
    """
    return getattr(request.state, "expected_version", None)
