from __future__ import annotations

import logging
import threading
import weakref
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from arclith.adapters.outbound.opentelemetry.config import (
    resolve_opentelemetry_settings,
)
from arclith.adapters.outbound.opentelemetry.correlation import (
    OpenTelemetryCorrelationContext,
)
from arclith.adapters.outbound.opentelemetry.logging import (
    OpenTelemetryLogRecordAdapter,
)
from arclith.adapters.outbound.opentelemetry.metrics import (
    OpenTelemetryMetricAdapter,
)
from arclith.adapters.outbound.opentelemetry.propagation import (
    OpenTelemetryContextPropagator,
)
from arclith.adapters.outbound.opentelemetry.provider_lifecycle import (
    _ManagedProviderState,
    _OpenTelemetryProviderLifecycle,
)
from arclith.adapters.outbound.opentelemetry.tracing import (
    OpenTelemetryTraceAdapter,
)
from arclith.domain.ports.outbound.logger import Logger
from arclith.domain.ports.outbound.observability import (
    ContextPropagatorPort,
    CorrelationContextPort,
    LogRecordPort,
    MetricPort,
    ObservabilityRuntimePort,
    TracePort,
)
from arclith.infrastructure.config import OpenTelemetrySettings


class OpenTelemetryRuntime(_OpenTelemetryProviderLifecycle, ObservabilityRuntimePort):
    """Lazy OpenTelemetry runtime owning only the resources it creates."""

    def __init__(
        self,
        settings: OpenTelemetrySettings,
        logger: Logger,
        *,
        service_name: str,
        service_version: str,
        overrides: dict[str, Any] | None = None,
    ) -> None:
        self.settings = settings
        self._logger = logger
        self._service_name = service_name
        self._service_version = service_version
        self._overrides = dict(overrides or {})
        self._lock = threading.RLock()
        self._started = False
        self._closed = False
        self._resolved: OpenTelemetrySettings | None = None
        self._trace_provider: Any | None = None
        self._meter_provider: Any | None = None
        self._logger_provider: Any | None = None
        self._log_handler: logging.Handler | None = None
        self._owned_processors: list[Any] = []
        self._attachment_keys: list[tuple[int, str, str]] = []
        self._managed_state: _ManagedProviderState | None = None
        self._httpx_instrumented = False
        self._fastapi_apps: list[weakref.ReferenceType[Any]] = []
        self._propagation = OpenTelemetryContextPropagator(settings.propagation)
        self._correlation: CorrelationContextPort = OpenTelemetryCorrelationContext(
            self._correlation_enabled
        )
        self._tracing = OpenTelemetryTraceAdapter(
            ensure_started=self.start,
            tracer_provider=self._require_trace_provider,
            propagator=self._propagation,
            capture=settings.capture,
            enabled=lambda: self._signal_enabled("traces"),
            flush=self.force_flush,
            shutdown=self.shutdown,
            diagnostics=self.diagnostics,
        )
        self._metrics = OpenTelemetryMetricAdapter(
            ensure_started=self.start,
            meter_provider=self._require_meter_provider,
            enabled=lambda: self._signal_enabled("metrics"),
        )
        self._logs = OpenTelemetryLogRecordAdapter(
            ensure_started=self.start,
            handler=lambda: self._log_handler,
            enabled=lambda: self._started and self._signal_enabled("logs"),
        )

    @property
    def tracer(self) -> TracePort:
        return self._tracing

    @property
    def metrics(self) -> MetricPort:
        return self._metrics

    @property
    def correlation(self) -> CorrelationContextPort:
        return self._correlation

    @property
    def propagator(self) -> ContextPropagatorPort:
        return self._propagation

    @property
    def logs(self) -> LogRecordPort:
        return self._logs

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("Le runtime OpenTelemetry est deja ferme")
            if self._started:
                return
            resolved = resolve_opentelemetry_settings(
                self.settings,
                service_name=self._service_name,
                service_version=self._service_version,
                overrides=self._overrides,
            )
            self._resolved = resolved
            self._propagation.configure(resolved.propagation)
            if self._has_enabled_signal(resolved):
                self._require_sdk()
                if resolved.mode == "managed":
                    self._start_managed(resolved)
                elif resolved.mode == "attach":
                    self._start_attach(resolved)
                else:
                    self._start_external(resolved)
                self._configure_log_handler(resolved)
                self._instrument_httpx(resolved)
            self._started = True
            self._logger.info(
                "OpenTelemetry runtime initialise",
                mode=resolved.mode,
                service_name=resolved.service.name,
                traces=resolved.signals.traces.enabled,
                metrics=resolved.signals.metrics.enabled,
                logs=resolved.signals.logs.enabled,
            )

    def instrument_fastapi(self, app: Any) -> None:
        if self._closed:
            raise RuntimeError("Le runtime OpenTelemetry est deja ferme")
        settings = self._resolved or resolve_opentelemetry_settings(
            self.settings,
            service_name=self._service_name,
            service_version=self._service_version,
            overrides=self._overrides,
        )
        if not _fastapi_instrumentation_enabled(settings):
            return
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        except ImportError as exc:
            raise RuntimeError(
                'instrumentation.fastapi=true requiert "arclith[opentelemetry]"'
            ) from exc
        if any(reference() is app for reference in self._fastapi_apps):
            return
        self._instrument_fastapi_app(app, settings, FastAPIInstrumentor)
        self._fastapi_apps.append(weakref.ref(app))

    def _instrument_fastapi_app(
        self,
        app: Any,
        settings: OpenTelemetrySettings,
        instrumentor: Any,
    ) -> None:
        from opentelemetry import metrics, trace

        from arclith.adapters.outbound.opentelemetry.instrumentations.http import (
            sanitize_fastapi_request_span,
        )

        # Proxy providers create proxy instruments now and resolve the managed
        # providers when the FastAPI lifespan starts after the worker fork.
        trace_provider = self._trace_provider or trace.get_tracer_provider()
        meter_provider = self._meter_provider or metrics.get_meter_provider()
        instrumentor.instrument_app(
            app,
            tracer_provider=trace_provider,
            meter_provider=meter_provider,
            server_request_hook=sanitize_fastapi_request_span,
            excluded_urls=",".join(settings.instrumentation.excluded_urls) or None,
            http_capture_headers_server_request=(
                settings.capture.request_headers_allowlist or None
            ),
            http_capture_headers_server_response=(
                settings.capture.response_headers_allowlist or None
            ),
            http_capture_headers_sanitize_fields=[
                "authorization",
                "cookie",
                "set-cookie",
                "proxy-authorization",
            ],
            exclude_spans=["receive", "send"],
        )

    def pydantic_ai_instrumentation(self) -> Any | None:
        self.start()
        settings = self._require_resolved()
        if not (
            settings.signals.traces.enabled and settings.instrumentation.pydantic_ai
        ):
            return None
        try:
            from pydantic_ai.capabilities.instrumentation import Instrumentation
            from pydantic_ai.models.instrumented import InstrumentationSettings
        except ImportError as exc:
            raise RuntimeError(
                "L'instrumentation Pydantic AI requiert arclith[langgraph,opentelemetry]"
            ) from exc
        return Instrumentation(
            InstrumentationSettings(
                tracer_provider=self._trace_provider,
                meter_provider=self._meter_provider,
                include_content=settings.capture.genai_content,
                include_binary_content=False,
                include_model_request_parameters=False,
            )
        )

    def instrument_langgraph(self, graph: Any, *, name: str) -> Any:
        self.start()
        settings = self._require_resolved()
        if not settings.instrumentation.langgraph or not (
            settings.signals.traces.enabled or settings.signals.metrics.enabled
        ):
            return graph
        from arclith.adapters.outbound.opentelemetry.instrumentations.langgraph import (
            instrument_langgraph,
        )

        return instrument_langgraph(
            graph,
            self.tracer,
            self.metrics,
            name=name,
        )

    def force_flush(self, timeout: float | None = None) -> bool:
        if not self._started or self._closed:
            return True
        timeout_millis = max(
            1,
            int((timeout or self._require_resolved().flush_timeout_seconds) * 1000),
        )
        success = True
        for provider in self._owned_or_managed_providers():
            success = (
                self._flush_target(provider, timeout_millis, keyword=True) and success
            )
        for processor in self._owned_processors:
            success = (
                self._flush_target(processor, timeout_millis, keyword=False) and success
            )
        return success

    def _flush_target(self, target: Any, timeout_millis: int, *, keyword: bool) -> bool:
        force_flush = getattr(target, "force_flush", None)
        if not callable(force_flush):
            return True
        try:
            result = (
                force_flush(timeout_millis=timeout_millis)
                if keyword
                else force_flush(timeout_millis)
            )
            return result is not False
        except Exception as exc:
            self._handle_runtime_error("force_flush", exc)
            return False

    def shutdown(self, timeout: float | None = None) -> None:
        with self._lock:
            if self._closed:
                return
            if not self._started:
                self._uninstrument_fastapi()
                self._closed = True
                return
            self.force_flush(timeout)
            self._uninstrument_fastapi()
            self._uninstrument_httpx()
            if self._managed_state is not None:
                self._release_managed_state(timeout)
            elif self._attachment_keys:
                self._release_attachments()
            else:
                for processor in reversed(self._owned_processors):
                    try:
                        processor.shutdown()
                    except Exception as exc:
                        self._handle_runtime_error("processor.shutdown", exc)
            self._owned_processors.clear()
            self._log_handler = None
            self._closed = True

    def _uninstrument_fastapi(self) -> None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        except ImportError:
            return
        for reference in self._fastapi_apps:
            if app := reference():
                try:
                    FastAPIInstrumentor.uninstrument_app(app)
                except Exception as exc:
                    self._handle_runtime_error("fastapi.uninstrument", exc)
        self._fastapi_apps.clear()

    def diagnostics(self) -> dict[str, Any]:
        settings = self._resolved or self.settings
        return {
            "backend": "opentelemetry",
            "started": self._started,
            "closed": self._closed,
            "mode": settings.mode,
            "service": {
                "name": settings.service.name or self._service_name,
                "namespace": settings.service.namespace,
                "version": settings.service.version or self._service_version,
            },
            "signals": {
                "traces": settings.signals.traces.enabled,
                "metrics": settings.signals.metrics.enabled,
                "logs": settings.signals.logs.enabled,
                "log_correlation": settings.signals.logs.correlate,
            },
            "instrumentation": settings.instrumentation.model_dump(),
            "capture": settings.capture.model_dump(),
            "propagators": list(settings.propagation.propagators),
            "export": {
                "protocol": settings.export.protocol,
                "endpoint": _safe_diagnostic_endpoint(settings.export.endpoint),
                "headers_env": settings.export.headers_env,
            },
        }

    def native_providers(self) -> dict[str, Any]:
        self.start()
        return {
            key: value
            for key, value in {
                "tracer_provider": self._trace_provider,
                "meter_provider": self._meter_provider,
                "logger_provider": self._logger_provider,
            }.items()
            if value is not None
        }

    def _require_trace_provider(self) -> Any:
        if self._trace_provider is None:
            raise RuntimeError("Le signal OpenTelemetry traces n'est pas actif")
        return self._trace_provider

    def _require_meter_provider(self) -> Any:
        if self._meter_provider is None:
            raise RuntimeError("Le signal OpenTelemetry metrics n'est pas actif")
        return self._meter_provider

    def _require_resolved(self) -> OpenTelemetrySettings:
        if self._resolved is None:
            raise RuntimeError("Le runtime OpenTelemetry n'est pas initialise")
        return self._resolved

    def _signal_enabled(self, signal: str) -> bool:
        settings = self._resolved or self.settings
        return bool(getattr(settings.signals, signal).enabled)

    def _correlation_enabled(self) -> bool:
        settings = self._resolved or self.settings
        return settings.signals.logs.correlate and settings.signals.traces.enabled

    @staticmethod
    def _has_enabled_signal(settings: OpenTelemetrySettings) -> bool:
        return any(
            (
                settings.signals.traces.enabled,
                settings.signals.metrics.enabled,
                settings.signals.logs.enabled,
            )
        )

    @staticmethod
    def _require_sdk() -> None:
        try:
            import opentelemetry.sdk  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                'observability.enabled contient opentelemetry; installez "arclith[opentelemetry]"'
            ) from exc

    def _handle_runtime_error(self, operation: str, error: Exception) -> None:
        if self._require_resolved().failure_mode == "raise":
            raise error
        self._logger.warning(
            "Erreur OpenTelemetry ignoree",
            operation=operation,
            error_type=type(error).__name__,
        )


def _safe_diagnostic_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    authority = parsed.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parsed.scheme, authority, parsed.path, "", ""))


def _fastapi_instrumentation_enabled(settings: OpenTelemetrySettings) -> bool:
    return settings.instrumentation.fastapi and (
        settings.signals.traces.enabled or settings.signals.metrics.enabled
    )
