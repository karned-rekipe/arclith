from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from arclith.domain.ports.outbound.observability import ObservabilityRuntimePort


def instrument_fastapi_app(app: "FastAPI", runtime: "ObservabilityRuntimePort") -> None:
    """Compatibility entry point delegating ownership to the neutral runtime."""

    runtime.instrument_fastapi(app)
