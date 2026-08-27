from __future__ import annotations

import os

import pytest

from arclith.adapters.outbound.opentelemetry.runtime import OpenTelemetryRuntime
from arclith.domain.ports.outbound.logger import Logger, LogLevel
from arclith.infrastructure.config import OpenTelemetrySettings

pytestmark = pytest.mark.skipif(
    os.getenv("ARCLITH_OTEL_INTEGRATION") != "1",
    reason="set ARCLITH_OTEL_INTEGRATION=1 with a local OTLP Collector",
)


class _NullLogger(Logger):
    def log(self, level: LogLevel, message: str, **metadata: object) -> None:
        return None


def test_collector_accepts_traces_metrics_and_logs() -> None:
    settings = OpenTelemetrySettings.model_validate(
        {
            "mode": "managed",
            "export": {
                "endpoint": os.getenv("ARCLITH_OTEL_ENDPOINT", "http://127.0.0.1:4318"),
                "protocol": "http/protobuf",
                "compression": "none",
                "timeout_millis": 3000,
            },
            "signals": {
                "traces": {"enabled": True, "sampler": "always_on"},
                "metrics": {
                    "enabled": True,
                    "export_interval_millis": 1000,
                    "export_timeout_millis": 3000,
                },
                "logs": {"enabled": True, "correlate": True},
            },
            "instrumentation": {"fastapi": False, "httpx": False},
            "flush_timeout_seconds": 3.0,
        }
    )
    runtime = OpenTelemetryRuntime(
        settings,
        _NullLogger(),
        service_name="arclith-collector-smoke",
        service_version="test",
    )

    runtime.start()
    with runtime.tracer.span(
        "arclith.collector.smoke", metadata={"test.kind": "integration"}
    ) as span:
        runtime.metrics.add_counter(
            "arclith.collector.smoke.operations",
            attributes={"test.kind": "integration"},
        )
        runtime.logs.emit(
            "INFO",
            "OpenTelemetry Collector smoke",
            attributes={"test.kind": "integration"},
        )
        span.set_outputs({"status": "success"})

    assert runtime.force_flush(3.0) is True
    runtime.shutdown(3.0)
