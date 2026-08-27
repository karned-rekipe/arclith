from __future__ import annotations

from arclith.adapters.outbound.noop.observability import NoOpTraceAdapter
from arclith.domain.ports.outbound.logger import Logger
from arclith.domain.ports.outbound.observability import TraceAnonymizer, TracePort
from arclith.infrastructure.config import AppConfig


def build_trace_adapter(
    config: AppConfig,
    logger: Logger,
    *,
    anonymizer: TraceAnonymizer | None = None,
) -> TracePort:
    if not config.adapters.observability.is_enabled("langsmith"):
        return NoOpTraceAdapter()

    settings = config.adapters.langsmith
    if settings is None:
        raise RuntimeError(
            "observability.enabled contient langsmith mais adapters.langsmith est absent"
        )

    from arclith.adapters.outbound.langsmith.runtime import LangSmithRuntime

    return LangSmithRuntime(
        settings,
        logger,
        service_metadata={
            "service.name": config.app.name,
            "service.version": config.app.version,
        },
        opentelemetry_enabled=config.adapters.observability.is_enabled("opentelemetry"),
        anonymizer=anonymizer,
        before_start=lambda: _configure_shared_opentelemetry(config),
    )


def _configure_shared_opentelemetry(config: AppConfig) -> None:
    if not config.adapters.observability.is_enabled("opentelemetry"):
        return
    settings = config.adapters.opentelemetry
    if settings is None:
        return
    from arclith.adapters.outbound.opentelemetry.fastapi import configure_opentelemetry

    configure_opentelemetry(
        settings,
        service_name=config.app.name,
        service_version=config.app.version,
    )
