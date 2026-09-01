from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from arclith.adapters.outbound.noop.observability import NoOpObservabilityRuntime
from arclith.infrastructure.config import (
    AppConfig,
    LangSmithPropagationSettings,
    LangSmithSettings,
    OpenTelemetrySettings,
)
from arclith.infrastructure.observability_factory import (
    CompositeObservabilityRuntime,
    LangSmithObservabilityRuntime,
    _configure_shared_opentelemetry,
    build_observability_runtime,
    build_trace_adapter,
)


class RecordingLangSmithRuntime:
    def __init__(self, *, fastapi: bool = True) -> None:
        self.settings = SimpleNamespace(
            instrumentation=SimpleNamespace(fastapi=fastapi),
            propagation=LangSmithPropagationSettings(
                enabled=True,
                baggage_allowlist=["safe"],
                langsmith_headers=True,
                traceparent=True,
            ),
        )
        self.events: list[tuple[str, Any]] = []

    def start(self) -> None:
        self.events.append(("start", None))

    def attach_to_current_opentelemetry(self) -> None:
        self.events.append(("attach", None))

    def inject(self, carrier: dict[str, str]) -> None:
        carrier["traceparent"] = "test"

    @contextmanager
    def context(
        self, *, parent: Mapping[str, str] | None = None, **kwargs: Any
    ) -> Iterator[None]:
        self.events.append(("context", parent))
        yield

    def pydantic_ai_capability(self) -> str:
        return "pydantic-ai"

    def flush(self, timeout: float | None = None) -> None:
        self.events.append(("flush", timeout))

    def close(self, timeout: float | None = None) -> None:
        self.events.append(("close", timeout))

    def diagnostics(self) -> dict[str, str]:
        return {"backend": "langsmith"}

    def client(self) -> str:
        return "client"


class RecordingOtelRuntime(NoOpObservabilityRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, Any]] = []

    def start(self) -> None:
        self.events.append(("start", None))

    def instrument_fastapi(self, app: Any) -> None:
        self.events.append(("fastapi", app))

    def pydantic_ai_instrumentation(self) -> str:
        return "otel-pydantic"

    def force_flush(self, timeout: float | None = None) -> bool:
        self.events.append(("flush", timeout))
        return True

    def shutdown(self, timeout: float | None = None) -> None:
        self.events.append(("shutdown", timeout))

    def diagnostics(self) -> dict[str, str]:
        return {"backend": "opentelemetry"}

    def native_providers(self) -> dict[str, str]:
        return {"tracer_provider": "provider"}


def test_langsmith_runtime_adapts_every_neutral_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = RecordingLangSmithRuntime()
    runtime = LangSmithObservabilityRuntime(raw)
    app = object()
    instrumented: list[tuple[Any, Any, Any]] = []
    monkeypatch.setattr(
        "arclith.adapters.outbound.langsmith.fastapi.instrument_fastapi_app",
        lambda target, adapter, *, propagation: instrumented.append(
            (target, adapter, propagation)
        ),
    )
    carrier: dict[str, str] = {}

    runtime.start()
    assert runtime.propagator.extract(
        {
            "LangSmith-Trace": "parent",
            "TraceParent": "w3c-parent",
            "TraceState": "vendor=value",
            "Baggage": "safe=yes,secret=no",
            "Authorization": "Bearer sensitive",
        }
    ) == {
        "langsmith-trace": "parent",
        "traceparent": "w3c-parent",
        "tracestate": "vendor=value",
        "baggage": "safe=yes",
    }
    runtime.propagator.inject(carrier)
    with runtime.propagator.context(carrier):
        pass
    runtime.instrument_fastapi(app)

    assert runtime.tracer is raw
    assert runtime.metrics is not None
    assert runtime.correlation.current() == {}
    assert runtime.logs is not None
    assert carrier == {"traceparent": "test"}
    assert instrumented == [(app, raw, raw.settings.propagation)]
    assert runtime.pydantic_ai_instrumentation() == "pydantic-ai"
    assert runtime.force_flush(1.5) is True
    runtime.shutdown(2.5)
    assert runtime.diagnostics() == {"backend": "langsmith"}
    assert runtime.client() == "client"


def test_langsmith_fastapi_instrumentation_respects_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = RecordingLangSmithRuntime(fastapi=False)
    runtime = LangSmithObservabilityRuntime(raw)
    monkeypatch.setattr(
        "arclith.adapters.outbound.langsmith.fastapi.instrument_fastapi_app",
        lambda app, adapter: pytest.fail("instrumentation must remain disabled"),
    )

    runtime.instrument_fastapi(object())


def test_langsmith_propagator_extract_respects_disabled_propagation() -> None:
    raw = RecordingLangSmithRuntime()
    raw.settings.propagation.enabled = False
    runtime = LangSmithObservabilityRuntime(raw)

    assert (
        runtime.propagator.extract(
            {"langsmith-trace": "parent", "traceparent": "w3c-parent"}
        )
        == {}
    )


def test_composite_runtime_keeps_one_otel_tree_and_delegates_lifecycle() -> None:
    otel = RecordingOtelRuntime()
    langsmith = RecordingLangSmithRuntime()
    runtime = CompositeObservabilityRuntime(otel, langsmith)
    app = object()

    runtime.start()
    runtime.instrument_fastapi(app)

    assert runtime.tracer is otel.tracer
    assert runtime.metrics is otel.metrics
    assert runtime.correlation is otel.correlation
    assert runtime.propagator is otel.propagator
    assert runtime.logs is otel.logs
    assert runtime.pydantic_ai_instrumentation() == "otel-pydantic"
    assert runtime.force_flush(3.0) is True
    assert runtime.native_providers() == {"tracer_provider": "provider"}
    assert runtime.client() == "client"
    assert runtime.diagnostics() == {
        "backend": "composite",
        "opentelemetry": {"backend": "opentelemetry"},
        "langsmith": {"backend": "langsmith"},
    }
    runtime.shutdown(4.0)

    assert otel.events == [
        ("start", None),
        ("fastapi", app),
        ("flush", 3.0),
        ("shutdown", 4.0),
    ]
    assert langsmith.events == [
        ("start", None),
        ("attach", None),
        ("flush", 3.0),
        ("close", 4.0),
    ]


def test_factory_returns_noop_and_backward_compatible_tracer(logger) -> None:
    config = AppConfig()

    runtime = build_observability_runtime(config, logger)

    assert isinstance(runtime, NoOpObservabilityRuntime)
    assert build_trace_adapter(config, logger) is not None
    assert _configure_shared_opentelemetry(config) is None


def test_factory_defensively_rejects_selected_backend_without_settings(logger) -> None:
    config = AppConfig()
    config.adapters.observability.enabled = ["opentelemetry"]

    with pytest.raises(RuntimeError, match="opentelemetry est absent"):
        build_observability_runtime(config, logger)

    config.adapters.observability.enabled = ["langsmith"]
    config.adapters.langsmith = None
    with pytest.raises(RuntimeError, match="langsmith est absent"):
        build_observability_runtime(config, logger)


def test_factory_builds_langsmith_only_runtime(
    logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = RecordingLangSmithRuntime()
    config = AppConfig()
    config.adapters.observability.enabled = ["langsmith"]
    config.adapters.langsmith = LangSmithSettings(project="tests")
    monkeypatch.setattr(
        "arclith.adapters.outbound.langsmith.runtime.LangSmithRuntime",
        lambda *args, **kwargs: raw,
    )

    runtime = build_observability_runtime(config, logger)

    assert isinstance(runtime, LangSmithObservabilityRuntime)
    assert runtime.tracer is raw


def test_factory_composite_starts_opentelemetry_once(
    logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    otel = RecordingOtelRuntime()
    langsmith = RecordingLangSmithRuntime()
    constructor_options: dict[str, Any] = {}
    config = AppConfig()
    config.adapters.observability.enabled = ["opentelemetry", "langsmith"]
    config.adapters.opentelemetry = OpenTelemetrySettings()
    config.adapters.langsmith = LangSmithSettings(project="tests")
    monkeypatch.setattr(
        "arclith.adapters.outbound.opentelemetry.runtime.OpenTelemetryRuntime",
        lambda *args, **kwargs: otel,
    )

    def build_langsmith(*args: Any, **kwargs: Any) -> RecordingLangSmithRuntime:
        constructor_options.update(kwargs)
        return langsmith

    monkeypatch.setattr(
        "arclith.adapters.outbound.langsmith.runtime.LangSmithRuntime",
        build_langsmith,
    )

    runtime = build_observability_runtime(config, logger)
    runtime.start()

    assert isinstance(runtime, CompositeObservabilityRuntime)
    assert "before_start" not in constructor_options
    assert otel.events == [("start", None)]
    assert langsmith.events == [("start", None), ("attach", None)]
