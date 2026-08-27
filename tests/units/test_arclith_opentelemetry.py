from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from arclith import Arclith
from arclith.adapters.outbound.noop.observability import NoOpObservabilityRuntime
from arclith.adapters.outbound.opentelemetry.runtime import OpenTelemetryRuntime
from arclith.arclith import _UvicornLogInterceptHandler
from arclith.domain.ports.outbound.logger import Logger, LogLevel
from arclith.infrastructure.observability_factory import (
    CompositeObservabilityRuntime,
)


class CapturingLogger(Logger):
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def log(self, level: LogLevel, message: str, **metadata: Any) -> None:
        self.records.append({"level": level, "message": message, "metadata": metadata})


class RecordingRuntime(NoOpObservabilityRuntime):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def instrument_fastapi(self, app: Any) -> None:
        self.events.append("runtime")


class InjectedCorrelation:
    def current(self) -> dict[str, str | bool]:
        return {}

    def from_log_record(self, record: Any) -> dict[str, str | bool]:
        return {
            "trace_id": record.otelTraceID,
            "span_id": record.otelSpanID,
            "trace_sampled": record.otelTraceSampled,
        }


def _make_config_dir(tmp_path: Path, *, langsmith: bool = False) -> Path:
    config_dir = tmp_path / "config"
    (config_dir / "adapters" / "outbound").mkdir(parents=True)
    (config_dir / "app.yaml").write_text(
        yaml.dump({"name": "demo-api", "version": "1.2.3"}),
        encoding="utf-8",
    )
    enabled = ["opentelemetry"]
    if langsmith:
        enabled.append("langsmith")
        (config_dir / "adapters" / "outbound" / "langsmith.yaml").write_text(
            yaml.dump({"project": "agent-tests", "tracing": {"enabled": False}}),
            encoding="utf-8",
        )
    (config_dir / "adapters" / "adapters.yaml").write_text(
        yaml.dump({"observability": {"enabled": enabled}}),
        encoding="utf-8",
    )
    (config_dir / "adapters" / "outbound" / "opentelemetry.yaml").write_text(
        yaml.dump(
            {
                "signals": {
                    "traces": {"enabled": False},
                    "metrics": {"enabled": False},
                    "logs": {"enabled": False},
                }
            }
        ),
        encoding="utf-8",
    )
    return config_dir


def test_arclith_builds_opentelemetry_runtime_only_when_selected(
    tmp_path: Path,
) -> None:
    arclith = Arclith(_make_config_dir(tmp_path))

    assert isinstance(arclith._observability_runtime, OpenTelemetryRuntime)
    assert arclith.observability_diagnostics()["service"]["name"] == "demo-api"
    assert arclith.observability_diagnostics()["started"] is False


def test_parallel_backends_build_one_composite_runtime(tmp_path: Path) -> None:
    arclith = Arclith(_make_config_dir(tmp_path, langsmith=True))

    assert isinstance(arclith._observability_runtime, CompositeObservabilityRuntime)
    diagnostics = arclith.observability_diagnostics()
    assert diagnostics["backend"] == "composite"
    assert set(diagnostics) == {"backend", "opentelemetry", "langsmith"}


def test_fastapi_delegates_instrumentation_to_neutral_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    events: list[str] = []

    monkeypatch.setattr(
        Arclith,
        "_add_fastapi_observability",
        lambda self, app: events.append("observability"),
    )
    monkeypatch.setattr(
        Arclith,
        "_add_fastapi_http_middlewares",
        lambda self, app: events.append("http"),
    )
    arclith = Arclith(_make_config_dir(tmp_path))
    arclith.__dict__["_observability_runtime"] = RecordingRuntime(events)

    arclith.fastapi()

    assert events == ["observability", "http", "runtime"]


def test_uvicorn_log_interceptor_uses_neutral_correlation_port() -> None:
    logger = CapturingLogger()
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, "request finished", (), None
    )
    record.otelTraceID = "0" * 31 + "1"
    record.otelSpanID = "0" * 15 + "2"
    record.otelTraceSampled = True

    _UvicornLogInterceptHandler(logger, InjectedCorrelation()).emit(record)  # type: ignore[arg-type]

    assert logger.records == [
        {
            "level": LogLevel.INFO,
            "message": "request finished",
            "metadata": {
                "trace_id": "0" * 31 + "1",
                "span_id": "0" * 15 + "2",
                "trace_sampled": True,
            },
        }
    ]


def test_base_import_does_not_load_opentelemetry_when_disabled() -> None:
    script = """
import sys
from arclith import Arclith
assert not any(name.startswith('opentelemetry') for name in sys.modules)
print('clean')
"""

    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "clean"
