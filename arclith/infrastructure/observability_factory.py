from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from typing import Any

from arclith.adapters.outbound.noop.observability import (
    NoOpCorrelationContext,
    NoOpLogRecordAdapter,
    NoOpMetricAdapter,
    NoOpObservabilityRuntime,
)
from arclith.domain.ports.outbound.logger import Logger
from arclith.domain.ports.outbound.observability import (
    ContextPropagatorPort,
    CorrelationContextPort,
    LogRecordPort,
    MetricPort,
    ObservabilityRuntimePort,
    TraceAnonymizer,
    TracePort,
)
from arclith.infrastructure.config import AppConfig, LangSmithPropagationSettings


def build_observability_runtime(
    config: AppConfig,
    logger: Logger,
    *,
    anonymizer: TraceAnonymizer | None = None,
    opentelemetry_overrides: Mapping[str, Any] | None = None,
) -> ObservabilityRuntimePort:
    otel_enabled = config.adapters.observability.is_enabled("opentelemetry")
    langsmith_enabled = config.adapters.observability.is_enabled("langsmith")
    if not otel_enabled and not langsmith_enabled:
        return NoOpObservabilityRuntime()

    otel_runtime = _build_opentelemetry_runtime(
        config,
        logger,
        enabled=otel_enabled,
        overrides=opentelemetry_overrides,
    )
    langsmith_runtime = _build_langsmith_runtime(
        config,
        logger,
        enabled=langsmith_enabled,
        opentelemetry_enabled=otel_enabled,
        anonymizer=anonymizer,
    )

    if otel_runtime is not None and langsmith_runtime is not None:
        return CompositeObservabilityRuntime(otel_runtime, langsmith_runtime)
    if otel_runtime is not None:
        return otel_runtime
    return LangSmithObservabilityRuntime(langsmith_runtime)


def _build_opentelemetry_runtime(
    config: AppConfig,
    logger: Logger,
    *,
    enabled: bool,
    overrides: Mapping[str, Any] | None,
) -> ObservabilityRuntimePort | None:
    if not enabled:
        return None
    settings = config.adapters.opentelemetry
    if settings is None:
        raise RuntimeError(
            "observability.enabled contient opentelemetry mais "
            "adapters.opentelemetry est absent"
        )
    from arclith.adapters.outbound.opentelemetry.runtime import OpenTelemetryRuntime

    return OpenTelemetryRuntime(
        settings,
        logger,
        service_name=config.app.name,
        service_version=config.app.version,
        overrides=dict(overrides or {}),
    )


def _build_langsmith_runtime(
    config: AppConfig,
    logger: Logger,
    *,
    enabled: bool,
    opentelemetry_enabled: bool,
    anonymizer: TraceAnonymizer | None,
) -> Any | None:
    if not enabled:
        return None
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
        opentelemetry_enabled=opentelemetry_enabled,
        anonymizer=anonymizer,
    )


def build_trace_adapter(
    config: AppConfig,
    logger: Logger,
    *,
    anonymizer: TraceAnonymizer | None = None,
) -> TracePort:
    """Backward-compatible factory returning the runtime's neutral tracer."""

    return build_observability_runtime(
        config,
        logger,
        anonymizer=anonymizer,
    ).tracer


def _configure_shared_opentelemetry(config: AppConfig) -> None:
    """Deprecated compatibility hook; composition now belongs to the runtime."""

    return None


class _TraceContextPropagator(ContextPropagatorPort):
    def __init__(
        self,
        tracer: TracePort,
        settings: LangSmithPropagationSettings,
    ) -> None:
        self._tracer = tracer
        self._settings = settings

    def inject(self, carrier: MutableMapping[str, str]) -> None:
        self._tracer.inject(carrier)

    def extract(self, carrier: Mapping[str, str]) -> Mapping[str, str]:
        from arclith.adapters.outbound.langsmith.propagation import (
            normalized_parent_headers,
        )

        if not self._settings.enabled:
            return {}
        return normalized_parent_headers(
            carrier,
            allowlist=set(self._settings.baggage_allowlist),
            langsmith_headers=self._settings.langsmith_headers,
            traceparent=self._settings.traceparent,
        )

    @contextmanager
    def context(self, carrier: Mapping[str, str] | None = None) -> Iterator[None]:
        with self._tracer.context(parent=carrier):
            yield


class LangSmithObservabilityRuntime(ObservabilityRuntimePort):
    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self._metrics = NoOpMetricAdapter()
        self._correlation = NoOpCorrelationContext()
        self._propagator = _TraceContextPropagator(
            runtime,
            runtime.settings.propagation,
        )
        self._logs = NoOpLogRecordAdapter()

    @property
    def tracer(self) -> TracePort:
        return self._runtime

    @property
    def metrics(self) -> MetricPort:
        return self._metrics

    @property
    def correlation(self) -> CorrelationContextPort:
        return self._correlation

    @property
    def propagator(self) -> ContextPropagatorPort:
        return self._propagator

    @property
    def logs(self) -> LogRecordPort:
        return self._logs

    def start(self) -> None:
        self._runtime.start()

    def instrument_fastapi(self, app: Any) -> None:
        if not self._runtime.settings.instrumentation.fastapi:
            return
        from arclith.adapters.outbound.langsmith.fastapi import instrument_fastapi_app

        instrument_fastapi_app(app, self._runtime)

    def pydantic_ai_instrumentation(self) -> Any | None:
        return self._runtime.pydantic_ai_capability()

    def force_flush(self, timeout: float | None = None) -> bool:
        self._runtime.flush(timeout)
        return True

    def shutdown(self, timeout: float | None = None) -> None:
        self._runtime.close(timeout)

    def diagnostics(self) -> Mapping[str, Any]:
        return self._runtime.diagnostics()

    def client(self) -> Any:
        return self._runtime.client()


class CompositeObservabilityRuntime(ObservabilityRuntimePort):
    """Compose OTLP and LangSmith around a single OpenTelemetry span tree."""

    def __init__(self, otel: ObservabilityRuntimePort, langsmith: Any) -> None:
        self._otel = otel
        self._langsmith = langsmith

    @property
    def tracer(self) -> TracePort:
        return self._otel.tracer

    @property
    def metrics(self) -> MetricPort:
        return self._otel.metrics

    @property
    def correlation(self) -> CorrelationContextPort:
        return self._otel.correlation

    @property
    def propagator(self) -> ContextPropagatorPort:
        return self._otel.propagator

    @property
    def logs(self) -> LogRecordPort:
        return self._otel.logs

    def start(self) -> None:
        self._otel.start()
        self._langsmith.start()
        self._langsmith.attach_to_current_opentelemetry()

    def instrument_fastapi(self, app: Any) -> None:
        self._otel.instrument_fastapi(app)

    def pydantic_ai_instrumentation(self) -> Any | None:
        return self._otel.pydantic_ai_instrumentation()

    def instrument_langgraph(self, graph: Any, *, name: str) -> Any:
        return self._otel.instrument_langgraph(graph, name=name)

    def force_flush(self, timeout: float | None = None) -> bool:
        self._langsmith.flush(timeout)
        return self._otel.force_flush(timeout)

    def shutdown(self, timeout: float | None = None) -> None:
        self._langsmith.close(timeout)
        self._otel.shutdown(timeout)

    def diagnostics(self) -> Mapping[str, Any]:
        return {
            "backend": "composite",
            "opentelemetry": self._otel.diagnostics(),
            "langsmith": self._langsmith.diagnostics(),
        }

    def native_providers(self) -> Mapping[str, Any]:
        return self._otel.native_providers()

    def client(self) -> Any:
        return self._langsmith.client()
