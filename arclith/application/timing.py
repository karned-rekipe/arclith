from __future__ import annotations

import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from arclith.domain.ports.outbound.logger import Logger


@asynccontextmanager
async def log_duration(logger: "Logger", operation: str, **ctx: Any) -> AsyncIterator[None]:
    """Async context manager — logs duration of any block.

    Usage::

        async with log_duration(self._logger, "service.create", entity="Ingredient"):
            result = await self._create.execute(entity)

    Logs ``⏱ <operation>  duration_ms=<x>  ok=True|False`` on exit.

    OTEL-ready: replace the body with ``tracer.start_as_current_span(operation)``
    when migrating to OpenTelemetry — call sites are unchanged.
    """
    start = time.monotonic()
    ok = True
    try:
        yield
    except Exception:
        ok = False
        raise
    finally:
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        logger.info(f"⏱ {operation}", duration_ms=duration_ms, ok=ok, **ctx)

