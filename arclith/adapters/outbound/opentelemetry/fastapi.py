import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

    from arclith.infrastructure.config import OpenTelemetrySettings

@dataclass
class _ConfigurationState:
    configured: bool = False


_CONFIGURATION_STATE = _ConfigurationState()


def instrument_fastapi_app(
    app: "FastAPI",
    settings: "OpenTelemetrySettings",
    *,
    service_name: str,
    service_version: str,
) -> None:
    if not (settings.traces or settings.metrics):
        return

    _configure_opentelemetry(settings, service_name=service_name, service_version=service_version)
    if not (settings.instrument_fastapi and settings.traces):
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError as exc:
        raise RuntimeError(
            'observability.enabled contient opentelemetry; installez l\'extra "arclith[opentelemetry]".'
        ) from exc

    FastAPIInstrumentor.instrument_app(app)


def _configure_opentelemetry(
    settings: "OpenTelemetrySettings",
    *,
    service_name: str,
    service_version: str,
) -> None:
    if _CONFIGURATION_STATE.configured or not (settings.traces or settings.metrics):
        return

    resource = _build_resource(settings, service_name=service_name, service_version=service_version)

    if settings.traces:
        _configure_traces(settings, resource)
    if settings.metrics:
        _configure_metrics(settings, resource)

    _instrument_logging_correlation()
    _CONFIGURATION_STATE.configured = True


def _build_resource(
    settings: "OpenTelemetrySettings",
    *,
    service_name: str,
    service_version: str,
) -> Any:
    try:
        from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
    except ImportError as exc:
        raise RuntimeError(
            'observability.enabled contient opentelemetry; installez l\'extra "arclith[opentelemetry]".'
        ) from exc

    return Resource.create({
        SERVICE_NAME: settings.service_name or service_name,
        SERVICE_VERSION: service_version,
    })


def _instrument_logging_correlation() -> None:
    try:
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
    except ImportError as exc:
        raise RuntimeError(
            'observability.enabled contient opentelemetry; installez l\'extra "arclith[opentelemetry]".'
        ) from exc

    LoggingInstrumentor().instrument(set_logging_format=False, inject_trace_context=True)


def _configure_traces(settings: "OpenTelemetrySettings", resource: Any) -> None:
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        raise RuntimeError(
            'observability.enabled contient opentelemetry; installez l\'extra "arclith[opentelemetry]".'
        ) from exc

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(_build_span_exporter(settings)))
    trace.set_tracer_provider(provider)


def _configure_metrics(settings: "OpenTelemetrySettings", resource: Any) -> None:
    try:
        from opentelemetry import metrics
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    except ImportError as exc:
        raise RuntimeError(
            'observability.enabled contient opentelemetry; installez l\'extra "arclith[opentelemetry]".'
        ) from exc

    reader = PeriodicExportingMetricReader(
        _build_metric_exporter(settings),
        export_interval_millis=settings.metrics_export_interval_millis,
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))


def _build_span_exporter(settings: "OpenTelemetrySettings") -> Any:
    headers = _headers_from_env(settings.headers_env)
    if settings.protocol == "grpc":
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GrpcSpanExporter

        return GrpcSpanExporter(endpoint=_resolve_endpoint(settings.traces_endpoint, settings.endpoint), headers=headers)

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HttpSpanExporter

    return HttpSpanExporter(
        endpoint=_resolve_endpoint(settings.traces_endpoint, settings.endpoint, suffix="v1/traces"),
        headers=headers,
    )


def _build_metric_exporter(settings: "OpenTelemetrySettings") -> Any:
    headers = _headers_from_env(settings.headers_env)
    if settings.protocol == "grpc":
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter as GrpcMetricExporter

        return GrpcMetricExporter(endpoint=_resolve_endpoint(settings.metrics_endpoint, settings.endpoint), headers=headers)

    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as HttpMetricExporter

    return HttpMetricExporter(
        endpoint=_resolve_endpoint(settings.metrics_endpoint, settings.endpoint, suffix="v1/metrics"),
        headers=headers,
    )


def _resolve_endpoint(explicit: str | None, base: str, suffix: str | None = None) -> str:
    if explicit:
        return explicit
    if suffix is None:
        return base
    return f"{base.rstrip('/')}/{suffix}"


def _headers_from_env(env_name: str) -> dict[str, str] | None:
    raw_headers = os.getenv(env_name, "").strip()
    if not raw_headers:
        return None

    headers: dict[str, str] = {}
    for item in raw_headers.split(","):
        key, separator, value = item.partition("=")
        key = key.strip()
        if separator == "=" and key:
            headers[key] = value.strip()
    return headers or None
