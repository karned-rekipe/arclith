from __future__ import annotations

from typing import Any

from arclith.adapters.outbound.opentelemetry.config import (
    exporter_headers,
    resolve_export_endpoint,
)
from arclith.infrastructure.config import OpenTelemetrySettings


def build_span_exporter(settings: OpenTelemetrySettings) -> Any:
    return _build_exporter(settings, "traces")


def build_metric_exporter(settings: OpenTelemetrySettings) -> Any:
    return _build_exporter(settings, "metrics")


def build_log_exporter(settings: OpenTelemetrySettings) -> Any:
    return _build_exporter(settings, "logs")


def _build_exporter(settings: OpenTelemetrySettings, signal: str) -> Any:
    endpoint = resolve_export_endpoint(settings, signal)
    headers = exporter_headers(settings, signal)
    timeout = settings.export.timeout_millis / 1000
    if settings.export.protocol == "grpc":
        import grpc

        exporter_class = _grpc_exporter(signal)
        compression = (
            grpc.Compression.Gzip
            if settings.export.compression == "gzip"
            else grpc.Compression.NoCompression
        )
        return exporter_class(
            endpoint=endpoint,
            headers=headers,
            timeout=timeout,
            insecure=settings.export.insecure,
            compression=compression,
        )

    from opentelemetry.exporter.otlp.proto.http import Compression

    exporter_class = _http_exporter(signal)
    compression = (
        Compression.Gzip
        if settings.export.compression == "gzip"
        else Compression.NoCompression
    )
    return exporter_class(
        endpoint=endpoint,
        headers=headers,
        timeout=timeout,
        compression=compression,
    )


def _grpc_exporter(signal: str) -> Any:
    if signal == "traces":
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        return OTLPSpanExporter
    if signal == "metrics":
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
            OTLPMetricExporter,
        )

        return OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

    return OTLPLogExporter


def _http_exporter(signal: str) -> Any:
    if signal == "traces":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        return OTLPSpanExporter
    if signal == "metrics":
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )

        return OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

    return OTLPLogExporter
