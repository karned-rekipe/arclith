"""Cache-Control middleware for HTTP caching strategy.

Implements industry-standard cache directives for different HTTP methods and resource types.
Critical for CDN integration, bandwidth optimization, and API performance.

RFC Reference: RFC 7234 (Caching)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from arclith.domain.ports.outbound.logger import Logger


class CacheControlMiddleware:
    """ASGI middleware that injects Cache-Control headers based on HTTP method and path.

    Strategy:
        GET (single resource):
            - Cache-Control: private, max-age=300
            - Cacheable by browser for 5 minutes
            - Not cacheable by shared CDN (contains user-specific data potentially)

        GET (list/collection):
            - Cache-Control: private, max-age=60
            - Shorter TTL due to frequent updates
            - Alternative: no-store for real-time data

        POST/PUT/PATCH/DELETE:
            - Cache-Control: no-cache, no-store, must-revalidate
            - Never cache mutations
            - Force revalidation

        Static resources (if handled):
            - Cache-Control: public, max-age=31536000, immutable
            - CDN-friendly for assets

    Configuration:
        - get_single_max_age: TTL for GET /{uuid} (default: 300s)
        - get_list_max_age: TTL for GET / (default: 60s)
        - mutations_no_store: Force no-store on mutations (default: True)
    """

    def __init__(
            self,
            app: Any,
            logger: "Logger",
            get_single_max_age: int = 300,  # 5 minutes
            get_list_max_age: int = 60,  # 1 minute
            mutations_no_store: bool = True,
    ) -> None:
        self._app = app
        self._logger = logger
        self._get_single_max_age = get_single_max_age
        self._get_list_max_age = get_list_max_age
        self._mutations_no_store = mutations_no_store

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")

        # Determine cache-control directive
        cache_control = self._get_cache_control(method, path)

        async def _send_wrapper(message: Any) -> None:
            if message["type"] == "http.response.start":
                # Inject Cache-Control header if not already present
                headers = list(message.get("headers", []))
                has_cache_control = any(k.lower() == b"cache-control" for k, _ in headers)

                if not has_cache_control and cache_control:
                    headers.append((b"cache-control", cache_control.encode()))
                    message = {**message, "headers": headers}
                    self._logger.debug(
                        "📦 Cache-Control injected",
                        method = method,
                        path = path,
                        directive = cache_control,
                    )

            await send(message)

        await self._app(scope, receive, _send_wrapper)

    def _get_cache_control(self, method: str, path: str) -> str | None:
        """Determine Cache-Control directive based on method and path."""
        # Mutations → no caching
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            if self._mutations_no_store:
                return "no-cache, no-store, must-revalidate"
            return "no-cache"

        # GET requests
        if method == "GET":
            # Heuristic: path ends with UUID → single resource
            # Otherwise → collection/list
            if self._is_single_resource_path(path):
                return f"private, max-age={self._get_single_max_age}"
            else:
                # Collection or list endpoint
                # Use shorter TTL or no-store for real-time data
                if self._get_list_max_age == 0:
                    return "no-store"
                return f"private, max-age={self._get_list_max_age}"

        # HEAD, OPTIONS → cacheable
        if method in {"HEAD", "OPTIONS"}:
            return "public, max-age=86400"  # 24 hours

        return None

    def _is_single_resource_path(self, path: str) -> bool:
        """Heuristic to detect single resource GET vs list GET.
        
        Examples:
            /v1/ingredients/01234... → True (single)
            /v1/ingredients → False (list)
            /v1/ingredients/search → False (action)
        """
        parts = [p for p in path.split("/") if p]
        if len(parts) < 2:
            return False

        last_part = parts[-1]

        # UUID-like pattern (hex, 8-4-4-4-12 format)
        # Simplified: if last segment is long hex string → likely UUID
        if len(last_part) >= 32 and all(c in "0123456789abcdefABCDEF-" for c in last_part):
            return True

        return False
