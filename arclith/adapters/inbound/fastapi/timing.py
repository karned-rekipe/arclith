from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from arclith.domain.ports.outbound.logger import Logger


class TimingMiddleware:
    """Starlette ASGI middleware — instruments every HTTP request.

    - Injects ``request.state.start_time`` so handlers can compute per-handler
      elapsed time via the ``get_duration_ms`` FastAPI dependency.
    - Appends ``X-Process-Time-Ms`` header to every response.
    - Emits a structured log line: method, path, status, duration_ms.

    Always active (independent of probe.enabled). Attached last in
    ``Arclith.fastapi()`` so it wraps the full middleware stack.
    """

    def __init__(self, app: Any, logger: "Logger") -> None:
        self._app = app
        self._logger = logger

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        start = time.monotonic()
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["start_time"] = start

        status_code = [500]

        async def _send_wrapper(message: Any) -> None:
            if message["type"] == "http.response.start":
                status_code[0] = message["status"]
                duration_ms = round((time.monotonic() - start) * 1000, 2)
                raw_headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                raw_headers.append((b"x-process-time-ms", str(duration_ms).encode()))
                message = {**message, "headers": raw_headers}
            await send(message)

        try:
            await self._app(scope, receive, _send_wrapper)
        finally:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            self._logger.info(
                "-> HTTP",
                method=scope.get("method", "?"),
                path=scope.get("path", "?"),
                status=status_code[0],
                duration_ms=duration_ms,
            )

