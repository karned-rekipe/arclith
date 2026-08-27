from __future__ import annotations

from typing import Any

import pytest

from arclith.adapters.outbound.opentelemetry.exporters import (
    build_log_exporter,
    build_metric_exporter,
    build_span_exporter,
)
from arclith.infrastructure.config import OpenTelemetrySettings


@pytest.mark.parametrize(
    ("builder", "signal", "class_fragment"),
    [
        (build_span_exporter, "traces", "Span"),
        (build_metric_exporter, "metrics", "Metric"),
        (build_log_exporter, "logs", "Log"),
    ],
)
@pytest.mark.parametrize(
    ("protocol", "port"),
    [("http/protobuf", 4318), ("grpc", 4317)],
)
def test_build_otlp_exporters_for_every_signal_and_protocol(
    builder: Any,
    signal: str,
    class_fragment: str,
    protocol: str,
    port: int,
) -> None:
    settings = OpenTelemetrySettings.model_validate(
        {
            "export": {
                "protocol": protocol,
                "endpoint": f"http://collector:{port}",
                "insecure": protocol == "grpc",
            }
        }
    )

    exporter = builder(settings)

    assert class_fragment in type(exporter).__name__
    exporter.shutdown()


def test_signal_specific_endpoint_takes_precedence(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "x-token=secret")
    settings = OpenTelemetrySettings.model_validate(
        {
            "export": {
                "traces_endpoint": "http://collector:4318/custom",
                "compression": "none",
            }
        }
    )

    exporter = build_span_exporter(settings)

    assert exporter._endpoint == "http://collector:4318/custom"
    assert exporter._headers["x-token"] == "secret"
    exporter.shutdown()
