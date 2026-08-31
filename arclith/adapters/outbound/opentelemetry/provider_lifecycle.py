from __future__ import annotations

import hashlib
import json
import logging
import threading
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any

from arclith.adapters.outbound.opentelemetry.exporters import (
    build_log_exporter,
    build_metric_exporter,
    build_span_exporter,
)
from arclith.adapters.outbound.opentelemetry.resource import build_resource
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


class _OpenTelemetryProviderLifecycle:
    """Own process-wide providers, processors, and HTTPX instrumentation."""

    _logger: Any
    _trace_provider: Any | None
    _meter_provider: Any | None
    _logger_provider: Any | None
    _log_handler: logging.Handler | None
    _owned_processors: list[Any]
    _attachment_keys: list[tuple[int, str, str]]
    _managed_state: _ManagedProviderState | None
    _httpx_instrumented: bool

    @abstractmethod
    def _require_resolved(self) -> OpenTelemetrySettings:
        raise NotImplementedError

    @abstractmethod
    def _handle_runtime_error(self, operation: str, error: Exception) -> None:
        raise NotImplementedError

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


def _configuration_fingerprint(settings: OpenTelemetrySettings) -> str:
    payload = settings.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _is_proxy_provider(provider: Any) -> bool:
    return "proxy" in type(provider).__name__.lower()


def _build_sampler(settings: OpenTelemetrySettings) -> Any:
    from opentelemetry.sdk.trace.sampling import (
        ALWAYS_OFF,
        ALWAYS_ON,
        ParentBased,
        TraceIdRatioBased,
    )

    traces = settings.signals.traces
    if traces.sampler == "always_on":
        return ALWAYS_ON
    if traces.sampler == "always_off":
        return ALWAYS_OFF
    if traces.sampler == "traceidratio":
        return TraceIdRatioBased(traces.sampling_ratio)
    if traces.sampler == "parentbased_always_on":
        return ParentBased(ALWAYS_ON)
    if traces.sampler == "parentbased_always_off":
        return ParentBased(ALWAYS_OFF)
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
