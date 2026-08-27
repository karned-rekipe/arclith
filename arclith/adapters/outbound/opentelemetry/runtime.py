from __future__ import annotations

import hashlib
import json
import logging
import threading
import weakref
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from arclith.adapters.outbound.opentelemetry.config import (
    resolve_opentelemetry_settings,
)
from arclith.adapters.outbound.opentelemetry.correlation import (
    OpenTelemetryCorrelationContext,
)
from arclith.adapters.outbound.opentelemetry.exporters import (
    build_log_exporter,
    build_metric_exporter,
    build_span_exporter,
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
from arclith.adapters.outbound.opentelemetry.resource import build_resource
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


@dataclass
class _ManagedProviderState:
    fingerprint: str
    trace_provider: Any | None
    meter_provider: Any | None
    logger_provider: Any | None
    references: int = 1
    closed: bool = False


@dataclass
class _AttachmentState:
    processor: Any
    references: int = 1


_PROCESS_LOCK = threading.RLock()
_MANAGED_STATE: _ManagedProviderState | None = None
_HTTPX_REFERENCES = 0
_ATTACHMENTS: dict[tuple[int, str, str], _AttachmentState] = {}


class OpenTelemetryRuntime(ObservabilityRuntimePort):
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

    def _start_managed(self, settings: OpenTelemetrySettings) -> None:
        global _MANAGED_STATE
        fingerprint = _configuration_fingerprint(settings)
        with _PROCESS_LOCK:
            if _MANAGED_STATE is not None:
                if _MANAGED_STATE.fingerprint != fingerprint:
                    raise RuntimeError(
                        "Configuration OpenTelemetry managed incompatible avec le runtime "
                        "deja installe dans ce processus"
                    )
                if _MANAGED_STATE.closed:
                    raise RuntimeError(
                        "Le provider OpenTelemetry managed global a deja ete ferme; "
                        "redemarrez le processus avant de recreer un runtime"
                    )
                _MANAGED_STATE.references += 1
                self._managed_state = _MANAGED_STATE
                self._adopt_managed_state(_MANAGED_STATE)
                return

            resource = build_resource(settings)
            self._assert_global_slots_available(settings)
            trace_provider = self._build_trace_provider(settings, resource)
            meter_provider = self._build_meter_provider(settings, resource)
            logger_provider = self._build_logger_provider(settings, resource)
            self._set_global_providers(
                trace_provider=trace_provider,
                meter_provider=meter_provider,
                logger_provider=logger_provider,
            )
            _MANAGED_STATE = _ManagedProviderState(
                fingerprint=fingerprint,
                trace_provider=trace_provider,
                meter_provider=meter_provider,
                logger_provider=logger_provider,
            )
            self._managed_state = _MANAGED_STATE
            self._adopt_managed_state(_MANAGED_STATE)

    def _start_attach(self, settings: OpenTelemetrySettings) -> None:
        from opentelemetry import metrics, trace
        from opentelemetry._logs import get_logger_provider

        if settings.signals.traces.enabled:
            trace_provider = trace.get_tracer_provider()
            if _is_proxy_provider(trace_provider) or not hasattr(
                trace_provider, "add_span_processor"
            ):
                raise RuntimeError(
                    "mode attach: aucun TracerProvider compatible n'est installe"
                )
            self._trace_provider = trace_provider
            self._attach_trace_processor(trace_provider, settings)
        if settings.signals.metrics.enabled:
            meter_provider = metrics.get_meter_provider()
            if _is_proxy_provider(meter_provider):
                raise RuntimeError(
                    "mode attach: aucun MeterProvider compatible n'est installe"
                )
            self._meter_provider = meter_provider
            self._logger.warning(
                "OpenTelemetry attach utilise le MeterProvider externe; "
                "les readers doivent etre configures par son proprietaire"
            )
        if settings.signals.logs.enabled:
            logger_provider = get_logger_provider()
            if _is_proxy_provider(logger_provider) or not hasattr(
                logger_provider, "add_log_record_processor"
            ):
                raise RuntimeError(
                    "mode attach: aucun LoggerProvider compatible n'est installe"
                )
            self._logger_provider = logger_provider
            self._attach_log_processor(logger_provider, settings)

    def _start_external(self, settings: OpenTelemetrySettings) -> None:
        from opentelemetry import metrics, trace
        from opentelemetry._logs import get_logger_provider

        if settings.signals.traces.enabled:
            self._trace_provider = trace.get_tracer_provider()
            if _is_proxy_provider(self._trace_provider):
                raise RuntimeError(
                    "mode external: aucun TracerProvider externe n'est installe"
                )
        if settings.signals.metrics.enabled:
            self._meter_provider = metrics.get_meter_provider()
            if _is_proxy_provider(self._meter_provider):
                raise RuntimeError(
                    "mode external: aucun MeterProvider externe n'est installe"
                )
        if settings.signals.logs.enabled:
            self._logger_provider = get_logger_provider()
            if _is_proxy_provider(self._logger_provider):
                raise RuntimeError(
                    "mode external: aucun LoggerProvider externe n'est installe"
                )

    def _assert_global_slots_available(self, settings: OpenTelemetrySettings) -> None:
        from opentelemetry import metrics, trace
        from opentelemetry._logs import get_logger_provider

        providers = (
            (
                "TracerProvider",
                settings.signals.traces.enabled,
                trace.get_tracer_provider(),
            ),
            (
                "MeterProvider",
                settings.signals.metrics.enabled,
                metrics.get_meter_provider(),
            ),
            (
                "LoggerProvider",
                settings.signals.logs.enabled,
                get_logger_provider(),
            ),
        )
        for name, enabled, provider in providers:
            if enabled and not _is_proxy_provider(provider):
                raise RuntimeError(
                    f"mode managed: un {name} global existe deja; "
                    "utilisez attach ou external"
                )

    def _set_global_providers(
        self,
        *,
        trace_provider: Any | None,
        meter_provider: Any | None,
        logger_provider: Any | None,
    ) -> None:
        if trace_provider is not None:
            from opentelemetry import trace

            trace.set_tracer_provider(trace_provider)
        if meter_provider is not None:
            from opentelemetry import metrics

            metrics.set_meter_provider(meter_provider)
        if logger_provider is not None:
            from opentelemetry._logs import set_logger_provider

            set_logger_provider(logger_provider)

    def _build_trace_provider(
        self, settings: OpenTelemetrySettings, resource: Any
    ) -> Any | None:
        if not settings.signals.traces.enabled:
            return None
        from opentelemetry.sdk.trace import SpanLimits, TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        limits = settings.limits
        provider = TracerProvider(
            sampler=_build_sampler(settings),
            resource=resource,
            shutdown_on_exit=False,
            span_limits=SpanLimits(
                max_attributes=limits.attribute_count,
                max_events=limits.span_event_count,
                max_links=limits.span_link_count,
                max_attribute_length=limits.attribute_value_length,
            ),
        )
        batch = settings.batch
        provider.add_span_processor(
            BatchSpanProcessor(
                build_span_exporter(settings),
                max_queue_size=batch.max_queue_size,
                schedule_delay_millis=batch.schedule_delay_millis,
                max_export_batch_size=batch.max_export_batch_size,
                export_timeout_millis=batch.export_timeout_millis,
            )
        )
        return provider

    def _build_meter_provider(
        self, settings: OpenTelemetrySettings, resource: Any
    ) -> Any | None:
        if not settings.signals.metrics.enabled:
            return None
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

        metric_settings = settings.signals.metrics
        reader = PeriodicExportingMetricReader(
            build_metric_exporter(settings),
            export_interval_millis=metric_settings.export_interval_millis,
            export_timeout_millis=metric_settings.export_timeout_millis,
        )
        return MeterProvider(
            metric_readers=[reader],
            resource=resource,
            shutdown_on_exit=False,
            exemplar_filter=_build_exemplar_filter(metric_settings.exemplar_filter),
        )

    def _build_logger_provider(
        self, settings: OpenTelemetrySettings, resource: Any
    ) -> Any | None:
        if not settings.signals.logs.enabled:
            return None
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

        batch = settings.batch
        provider = LoggerProvider(resource=resource, shutdown_on_exit=False)
        provider.add_log_record_processor(
            BatchLogRecordProcessor(
                build_log_exporter(settings),
                schedule_delay_millis=batch.schedule_delay_millis,
                max_export_batch_size=batch.max_export_batch_size,
                export_timeout_millis=batch.export_timeout_millis,
                max_queue_size=batch.max_queue_size,
            )
        )
        return provider

    def _attach_trace_processor(
        self, provider: Any, settings: OpenTelemetrySettings
    ) -> None:
        fingerprint = _configuration_fingerprint(settings)
        key = (id(provider), "traces", fingerprint)
        with _PROCESS_LOCK:
            state = _ATTACHMENTS.get(key)
            if state is None:
                from opentelemetry.sdk.trace.export import BatchSpanProcessor

                batch = settings.batch
                processor = BatchSpanProcessor(
                    build_span_exporter(settings),
                    max_queue_size=batch.max_queue_size,
                    schedule_delay_millis=batch.schedule_delay_millis,
                    max_export_batch_size=batch.max_export_batch_size,
                    export_timeout_millis=batch.export_timeout_millis,
                )
                provider.add_span_processor(processor)
                state = _AttachmentState(processor)
                _ATTACHMENTS[key] = state
            else:
                state.references += 1
            self._attachment_keys.append(key)
            self._owned_processors.append(state.processor)

    def _attach_log_processor(
        self, provider: Any, settings: OpenTelemetrySettings
    ) -> None:
        fingerprint = _configuration_fingerprint(settings)
        key = (id(provider), "logs", fingerprint)
        with _PROCESS_LOCK:
            state = _ATTACHMENTS.get(key)
            if state is None:
                from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

                batch = settings.batch
                processor = BatchLogRecordProcessor(
                    build_log_exporter(settings),
                    schedule_delay_millis=batch.schedule_delay_millis,
                    max_export_batch_size=batch.max_export_batch_size,
                    export_timeout_millis=batch.export_timeout_millis,
                    max_queue_size=batch.max_queue_size,
                )
                provider.add_log_record_processor(processor)
                state = _AttachmentState(processor)
                _ATTACHMENTS[key] = state
            else:
                state.references += 1
            self._attachment_keys.append(key)
            self._owned_processors.append(state.processor)

    def _configure_log_handler(self, settings: OpenTelemetrySettings) -> None:
        if not settings.signals.logs.enabled or self._logger_provider is None:
            return
        from opentelemetry.sdk._logs import LoggingHandler

        self._log_handler = LoggingHandler(
            level=logging.NOTSET,
            logger_provider=self._logger_provider,
        )

    def _instrument_httpx(self, settings: OpenTelemetrySettings) -> None:
        global _HTTPX_REFERENCES
        if not (settings.signals.traces.enabled and settings.instrumentation.httpx):
            return
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        except ImportError as exc:
            raise RuntimeError(
                "instrumentation.httpx=true requiert arclith[opentelemetry] "
                "avec opentelemetry-instrumentation-httpx"
            ) from exc
        with _PROCESS_LOCK:
            if _HTTPX_REFERENCES == 0:
                from arclith.adapters.outbound.opentelemetry.instrumentations.http import (
                    sanitize_async_httpx_request_span,
                    sanitize_httpx_request_span,
                )

                HTTPXClientInstrumentor().instrument(
                    tracer_provider=self._trace_provider,
                    meter_provider=self._meter_provider,
                    request_hook=sanitize_httpx_request_span,
                    async_request_hook=sanitize_async_httpx_request_span,
                )
            _HTTPX_REFERENCES += 1
            self._httpx_instrumented = True

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

    def _release_attachments(self) -> None:
        with _PROCESS_LOCK:
            for key in reversed(self._attachment_keys):
                state = _ATTACHMENTS.get(key)
                if state is None:
                    continue
                state.references -= 1
                if state.references > 0:
                    continue
                try:
                    state.processor.shutdown()
                except Exception as exc:
                    self._handle_runtime_error("processor.shutdown", exc)
                _ATTACHMENTS.pop(key, None)
        self._attachment_keys.clear()

    def _release_managed_state(self, timeout: float | None) -> None:
        state = self._managed_state
        if state is None:
            return
        with _PROCESS_LOCK:
            state.references -= 1
            if state.references > 0:
                return
            timeout_millis = max(
                1,
                int((timeout or self._require_resolved().flush_timeout_seconds) * 1000),
            )
            for provider in (
                state.logger_provider,
                state.meter_provider,
                state.trace_provider,
            ):
                if provider is None:
                    continue
                try:
                    shutdown = provider.shutdown
                    try:
                        shutdown(timeout_millis=timeout_millis)
                    except TypeError:
                        shutdown()
                except Exception as exc:
                    self._handle_runtime_error("provider.shutdown", exc)
            state.closed = True

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

    def _uninstrument_httpx(self) -> None:
        global _HTTPX_REFERENCES
        if not self._httpx_instrumented:
            return
        with _PROCESS_LOCK:
            _HTTPX_REFERENCES = max(0, _HTTPX_REFERENCES - 1)
            if _HTTPX_REFERENCES == 0:
                try:
                    from opentelemetry.instrumentation.httpx import (
                        HTTPXClientInstrumentor,
                    )

                    HTTPXClientInstrumentor().uninstrument()
                except Exception as exc:
                    self._handle_runtime_error("httpx.uninstrument", exc)
        self._httpx_instrumented = False

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

    def _adopt_managed_state(self, state: _ManagedProviderState) -> None:
        self._trace_provider = state.trace_provider
        self._meter_provider = state.meter_provider
        self._logger_provider = state.logger_provider

    def _owned_or_managed_providers(self) -> list[Any]:
        if self._managed_state is None:
            return []
        return [
            provider
            for provider in (
                self._managed_state.trace_provider,
                self._managed_state.meter_provider,
                self._managed_state.logger_provider,
            )
            if provider is not None
        ]

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


def _configuration_fingerprint(settings: OpenTelemetrySettings) -> str:
    payload = settings.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _is_proxy_provider(provider: Any) -> bool:
    return "proxy" in type(provider).__name__.lower()


def _safe_diagnostic_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    authority = parsed.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parsed.scheme, authority, parsed.path, "", ""))


def _fastapi_instrumentation_enabled(settings: OpenTelemetrySettings) -> bool:
    return settings.instrumentation.fastapi and (
        settings.signals.traces.enabled or settings.signals.metrics.enabled
    )


def _build_sampler(settings: OpenTelemetrySettings) -> Any:
    from opentelemetry.sdk.trace.sampling import (
        ALWAYS_OFF,
        ALWAYS_ON,
        ParentBased,
        TraceIdRatioBased,
    )

    traces = settings.signals.traces
    match traces.sampler:
        case "always_on":
            return ALWAYS_ON
        case "always_off":
            return ALWAYS_OFF
        case "traceidratio":
            return TraceIdRatioBased(traces.sampling_ratio)
        case "parentbased_always_on":
            return ParentBased(ALWAYS_ON)
        case "parentbased_always_off":
            return ParentBased(ALWAYS_OFF)
        case _:
            return ParentBased(TraceIdRatioBased(traces.sampling_ratio))


def _build_exemplar_filter(name: str) -> Any:
    from opentelemetry.sdk.metrics import (
        AlwaysOffExemplarFilter,
        AlwaysOnExemplarFilter,
        TraceBasedExemplarFilter,
    )

    if name == "always_on":
        return AlwaysOnExemplarFilter()
    if name == "always_off":
        return AlwaysOffExemplarFilter()
    return TraceBasedExemplarFilter()
