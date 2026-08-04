from __future__ import annotations

import asyncio
import platform
import sys
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any


class ProbeServer:
    """Lightweight HTTP server exposing /health, /ready, /info, /metrics.

    Runs in a daemon thread with its own asyncio event loop — completely
    independent of the main service transport (FastAPI, FastMCP, stdio…).
    """

    def __init__(self, host: str, port: int, service_name: str, service_version: str) -> None:
        self._host = host
        self._port = port
        self._service_name = service_name
        self._service_version = service_version
        self._start_time = time.monotonic()
        self._collectors: list[Any] = []
        self._readiness_checks: list[Callable[[], Awaitable[bool]]] = []
        self._active_transports: list[str] = []

    # ── registration ──────────────────────────────────────────────────────────

    def add_collector(self, collector: Any) -> None:
        self._collectors.append(collector)

    def add_readiness_check(self, fn: Callable[[], Awaitable[bool]]) -> None:
        self._readiness_checks.append(fn)

    def set_active_transports(self, transports: list[str]) -> None:
        self._active_transports = list(transports)

    # ── ASGI app ──────────────────────────────────────────────────────────────

    def _build_app(self) -> Any:
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        async def health(_: Request) -> JSONResponse:
            return JSONResponse({"status": "ok"})

        async def ready(_: Request) -> JSONResponse:
            if not self._readiness_checks:
                return JSONResponse({"status": "ready"})
            results = await asyncio.gather(
                *(fn() for fn in self._readiness_checks),
                return_exceptions=True,
            )
            ok = all(r is True for r in results)
            return JSONResponse(
                {"status": "ready" if ok else "not_ready"},
                status_code=200 if ok else 503,
            )

        async def info(_: Request) -> JSONResponse:
            return JSONResponse({
                "service": self._service_name,
                "version": self._service_version,
                "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                "platform": platform.system(),
                "uptime_s": round(time.monotonic() - self._start_time, 1),
                "active_transports": self._active_transports,
            })

        async def metrics(_: Request) -> JSONResponse:
            collected: dict[str, Any] = {}
            for collector in self._collectors:
                collected[collector.transport] = collector.collect()
            return JSONResponse({
                "collected_at": datetime.now(UTC).isoformat(),
                "transports": collected,
            })

        return Starlette(routes=[
            Route("/health", health),
            Route("/ready", ready),
            Route("/info", info),
            Route("/metrics", metrics),
        ])

    # ── launcher ──────────────────────────────────────────────────────────────

    def start_in_background(self) -> None:
        """Start the probe server in a daemon thread (non-blocking)."""

        def _run() -> None:
            import uvicorn
            config = uvicorn.Config(
                self._build_app(),
                host=self._host,
                port=self._port,
                log_config=None,
                access_log=False,
                ws="websockets-sansio",
            )
            server = uvicorn.Server(config)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server.serve())

        thread = threading.Thread(target=_run, daemon=True, name="probe-server")
        thread.start()


