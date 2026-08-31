from __future__ import annotations

import builtins
import io
from typing import Any

import pytest
from fastapi import FastAPI

from arclith.adapters.outbound.opentelemetry import (
    provider_lifecycle as provider_module,
)
from arclith.adapters.outbound.opentelemetry.runtime import OpenTelemetryRuntime
from arclith.infrastructure.config import OpenTelemetrySettings


class RecordingProvider:
    def __init__(self) -> None:
        self.flushes: list[int] = []
        self.shutdowns = 0

    def force_flush(self, timeout_millis: int) -> bool:
        self.flushes.append(timeout_millis)
        return True

    def shutdown(self, **kwargs: Any) -> None:
        self.shutdowns += 1

    def add_span_processor(self, processor: Any) -> None:
        self.processor = processor

    def add_log_record_processor(self, processor: Any) -> None:
        self.log_processor = processor


class FailingProvider(RecordingProvider):
    def force_flush(self, timeout_millis: int) -> bool:
        raise ValueError("flush failed")

    def shutdown(self, **kwargs: Any) -> None:
        raise ValueError("shutdown failed")


def _settings(
    *,
    mode: str = "managed",
    traces: bool = True,
    metrics: bool = False,
    logs: bool = False,
) -> OpenTelemetrySettings:
    return OpenTelemetrySettings.model_validate(
        {
            "mode": mode,
            "signals": {
                "traces": {"enabled": traces},
                "metrics": {"enabled": metrics},
                "logs": {"enabled": logs},
            },
            "instrumentation": {
                "fastapi": True,
                "httpx": False,
                "fastmcp": True,
                "rabbitmq": True,
                "pydantic_ai": True,
                "langgraph": True,
            },
        }
    )


def test_managed_runtime_is_idempotent_and_owns_shutdown(
    logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = RecordingProvider()
    monkeypatch.setattr(provider_module, "_MANAGED_STATE", None)
    runtime = OpenTelemetryRuntime(
        _settings(),
        logger,
        service_name="demo",
        service_version="1.0",
    )
    builds: list[str] = []
    monkeypatch.setattr(
        runtime, "_assert_global_slots_available", lambda settings: None
    )
    monkeypatch.setattr(
        runtime,
        "_build_trace_provider",
        lambda settings, resource: builds.append("traces") or provider,
    )
    monkeypatch.setattr(
        runtime, "_build_meter_provider", lambda settings, resource: None
    )
    monkeypatch.setattr(
        runtime, "_build_logger_provider", lambda settings, resource: None
    )
    monkeypatch.setattr(runtime, "_set_global_providers", lambda **providers: None)
    monkeypatch.setattr(provider_module, "build_resource", lambda settings: object())

    runtime.start()
    runtime.start()

    assert builds == ["traces"]
    assert runtime.force_flush(1.25) is True
    assert provider.flushes == [1250]
    runtime.shutdown(2.0)
    runtime.shutdown(2.0)
    assert provider.shutdowns == 1


def test_identical_managed_runtimes_share_providers_without_duplicates(
    logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = RecordingProvider()
    monkeypatch.setattr(provider_module, "_MANAGED_STATE", None)
    runtimes = [
        OpenTelemetryRuntime(
            _settings(), logger, service_name="demo", service_version="1.0"
        )
        for _ in range(2)
    ]
    builds = 0

    def build(settings: Any, resource: Any) -> RecordingProvider:
        nonlocal builds
        builds += 1
        return provider

    for runtime in runtimes:
        monkeypatch.setattr(
            runtime, "_assert_global_slots_available", lambda settings: None
        )
        monkeypatch.setattr(runtime, "_build_trace_provider", build)
        monkeypatch.setattr(
            runtime, "_build_meter_provider", lambda settings, resource: None
        )
        monkeypatch.setattr(
            runtime, "_build_logger_provider", lambda settings, resource: None
        )
        monkeypatch.setattr(runtime, "_set_global_providers", lambda **providers: None)
    monkeypatch.setattr(provider_module, "build_resource", lambda settings: object())

    runtimes[0].start()
    runtimes[1].start()
    assert builds == 1

    runtimes[0].shutdown()
    assert provider.shutdowns == 0
    runtimes[1].shutdown()
    assert provider.shutdowns == 1


def test_managed_runtime_rejects_incompatible_process_configuration(
    logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        provider_module,
        "_MANAGED_STATE",
        provider_module._ManagedProviderState("different", None, None, None),
    )
    runtime = OpenTelemetryRuntime(
        _settings(), logger, service_name="demo", service_version="1.0"
    )

    with pytest.raises(RuntimeError, match="incompatible"):
        runtime.start()


def test_external_runtime_never_flushes_or_closes_external_provider(
    logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = RecordingProvider()
    monkeypatch.setattr("opentelemetry.trace.get_tracer_provider", lambda: provider)
    runtime = OpenTelemetryRuntime(
        _settings(mode="external"),
        logger,
        service_name="demo",
        service_version="1.0",
    )

    runtime.start()
    assert runtime.force_flush(1.0) is True
    runtime.shutdown(1.0)

    assert provider.flushes == []
    assert provider.shutdowns == 0


def test_attach_runtimes_share_processor_until_last_shutdown(
    logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = RecordingProvider()
    processors: list[RecordingProvider] = []

    def processor_factory(*args: Any, **kwargs: Any) -> RecordingProvider:
        processor = RecordingProvider()
        processors.append(processor)
        return processor

    monkeypatch.setattr(provider_module, "_ATTACHMENTS", {})
    monkeypatch.setattr("opentelemetry.trace.get_tracer_provider", lambda: provider)
    monkeypatch.setattr(
        "opentelemetry.sdk.trace.export.BatchSpanProcessor", processor_factory
    )
    monkeypatch.setattr(
        provider_module, "build_span_exporter", lambda settings: object()
    )
    runtimes = [
        OpenTelemetryRuntime(
            _settings(mode="attach"),
            logger,
            service_name="demo",
            service_version="1.0",
        )
        for _ in range(2)
    ]

    runtimes[0].start()
    runtimes[1].start()
    assert len(processors) == 1

    runtimes[0].shutdown()
    assert processors[0].shutdowns == 0
    runtimes[1].shutdown()
    assert processors[0].shutdowns == 1


def test_fastapi_instrumentation_uses_owned_providers_and_safe_headers(
    logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = RecordingProvider()
    monkeypatch.setattr("opentelemetry.trace.get_tracer_provider", lambda: provider)
    calls: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(
        "opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app",
        lambda app, **kwargs: calls.append((app, kwargs)),
    )
    monkeypatch.setattr(
        "opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.uninstrument_app",
        lambda app: None,
    )
    settings = _settings(mode="external")
    settings.capture.request_headers_allowlist = ["x-request-id"]
    runtime = OpenTelemetryRuntime(
        settings, logger, service_name="demo", service_version="1.0"
    )
    app = FastAPI()

    runtime.instrument_fastapi(app)
    runtime.instrument_fastapi(app)

    assert len(calls) == 1
    assert calls[0][0] is app
    assert calls[0][1]["tracer_provider"] is provider
    assert callable(calls[0][1]["server_request_hook"])
    assert calls[0][1]["http_capture_headers_server_request"] == ["x-request-id"]
    assert "authorization" in calls[0][1]["http_capture_headers_sanitize_fields"]
    runtime.shutdown()


def test_diagnostics_never_include_exporter_header_values(logger) -> None:
    settings = _settings(traces=False)
    settings.export.endpoint = "https://user:password@collector.test/v1?token=secret"
    runtime = OpenTelemetryRuntime(
        settings,
        logger,
        service_name="demo",
        service_version="1.0",
    )

    diagnostics = runtime.diagnostics()

    assert diagnostics["export"]["headers_env"] == "OTEL_EXPORTER_OTLP_HEADERS"
    assert diagnostics["export"]["endpoint"] == "https://collector.test/v1"
    assert "headers" not in diagnostics["export"]
    assert "password" not in repr(diagnostics)
    assert "secret" not in repr(diagnostics)


def test_provider_builders_cover_all_signals_and_disabled_paths(
    logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    from opentelemetry.sdk._logs.export import ConsoleLogExporter
    from opentelemetry.sdk.metrics.export import ConsoleMetricExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter

    settings = _settings(traces=True, metrics=True, logs=True)
    runtime = OpenTelemetryRuntime(
        settings, logger, service_name="demo", service_version="1.0"
    )
    resource = Resource.create({"service.name": "demo"})
    output = io.StringIO()
    monkeypatch.setattr(
        provider_module,
        "build_span_exporter",
        lambda resolved: ConsoleSpanExporter(out=output),
    )
    monkeypatch.setattr(
        provider_module,
        "build_metric_exporter",
        lambda resolved: ConsoleMetricExporter(out=output),
    )
    monkeypatch.setattr(
        provider_module,
        "build_log_exporter",
        lambda resolved: ConsoleLogExporter(out=output),
    )

    providers = [
        runtime._build_trace_provider(settings, resource),
        runtime._build_meter_provider(settings, resource),
        runtime._build_logger_provider(settings, resource),
    ]

    assert all(provider is not None for provider in providers)
    for provider in reversed(providers):
        provider.shutdown()

    disabled = _settings(traces=False, metrics=False, logs=False)
    assert runtime._build_trace_provider(disabled, resource) is None
    assert runtime._build_meter_provider(disabled, resource) is None
    assert runtime._build_logger_provider(disabled, resource) is None


@pytest.mark.parametrize(
    ("sampler", "expected_type"),
    [
        ("always_on", "StaticSampler"),
        ("always_off", "StaticSampler"),
        ("traceidratio", "TraceIdRatioBased"),
        ("parentbased_always_on", "ParentBased"),
        ("parentbased_always_off", "ParentBased"),
        ("parentbased_traceidratio", "ParentBased"),
    ],
)
def test_sampler_variants(sampler: str, expected_type: str) -> None:
    settings = _settings()
    settings.signals.traces.sampler = sampler

    assert type(provider_module._build_sampler(settings)).__name__ == expected_type


@pytest.mark.parametrize(
    ("name", "expected_type"),
    [
        ("always_on", "AlwaysOnExemplarFilter"),
        ("always_off", "AlwaysOffExemplarFilter"),
        ("trace_based", "TraceBasedExemplarFilter"),
    ],
)
def test_exemplar_filter_variants(name: str, expected_type: str) -> None:
    assert type(provider_module._build_exemplar_filter(name)).__name__ == expected_type


def test_external_runtime_adopts_all_signal_providers_without_ownership(
    logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.trace import TracerProvider

    providers = {
        "tracer_provider": TracerProvider(shutdown_on_exit=False),
        "meter_provider": MeterProvider(shutdown_on_exit=False),
        "logger_provider": LoggerProvider(shutdown_on_exit=False),
    }
    monkeypatch.setattr(
        "opentelemetry.trace.get_tracer_provider",
        lambda: providers["tracer_provider"],
    )
    monkeypatch.setattr(
        "opentelemetry.metrics.get_meter_provider",
        lambda: providers["meter_provider"],
    )
    monkeypatch.setattr(
        "opentelemetry._logs.get_logger_provider",
        lambda: providers["logger_provider"],
    )
    runtime = OpenTelemetryRuntime(
        _settings(mode="external", traces=True, metrics=True, logs=True),
        logger,
        service_name="demo",
        service_version="1.0",
    )

    runtime.start()

    assert runtime.tracer is not None
    assert runtime.metrics is not None
    assert runtime.propagator is not None
    assert runtime.logs is not None
    assert runtime.native_providers() == providers
    assert runtime._require_trace_provider() is providers["tracer_provider"]
    assert runtime._require_meter_provider() is providers["meter_provider"]
    capability = runtime.pydantic_ai_instrumentation()
    assert capability.settings.include_content is False
    assert capability.settings.include_binary_content is False
    assert capability.settings.include_model_request_parameters is False
    runtime.shutdown()

    for provider in providers.values():
        provider.shutdown()


def test_attach_mode_installs_trace_and_log_processors_and_reuses_metrics(
    logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    trace_provider = RecordingProvider()
    meter_provider = object()
    logger_provider = RecordingProvider()
    processors: list[RecordingProvider] = []

    def processor_factory(*args: Any, **kwargs: Any) -> RecordingProvider:
        processor = RecordingProvider()
        processors.append(processor)
        return processor

    monkeypatch.setattr(provider_module, "_ATTACHMENTS", {})
    monkeypatch.setattr(
        "opentelemetry.trace.get_tracer_provider", lambda: trace_provider
    )
    monkeypatch.setattr(
        "opentelemetry.metrics.get_meter_provider", lambda: meter_provider
    )
    monkeypatch.setattr(
        "opentelemetry._logs.get_logger_provider", lambda: logger_provider
    )
    monkeypatch.setattr(
        "opentelemetry.sdk.trace.export.BatchSpanProcessor", processor_factory
    )
    monkeypatch.setattr(
        "opentelemetry.sdk._logs.export.BatchLogRecordProcessor", processor_factory
    )
    monkeypatch.setattr(
        provider_module, "build_span_exporter", lambda settings: object()
    )
    monkeypatch.setattr(
        provider_module, "build_log_exporter", lambda settings: object()
    )
    runtime = OpenTelemetryRuntime(
        _settings(mode="attach", traces=True, metrics=True, logs=True),
        logger,
        service_name="demo",
        service_version="1.0",
    )
    monkeypatch.setattr(runtime, "_configure_log_handler", lambda settings: None)

    runtime.start()

    assert runtime._trace_provider is trace_provider
    assert runtime._meter_provider is meter_provider
    assert runtime._logger_provider is logger_provider
    assert trace_provider.processor is processors[0]
    assert logger_provider.log_processor is processors[1]
    runtime.shutdown()
    assert [processor.shutdowns for processor in processors] == [1, 1]


@pytest.mark.parametrize(
    ("signal", "message"),
    [
        ("traces", "TracerProvider"),
        ("metrics", "MeterProvider"),
        ("logs", "LoggerProvider"),
    ],
)
def test_external_mode_rejects_missing_provider(
    signal: str, message: str, logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ProxyProvider:
        pass

    settings = _settings(
        mode="external",
        traces=signal == "traces",
        metrics=signal == "metrics",
        logs=signal == "logs",
    )
    monkeypatch.setattr(
        "opentelemetry.trace.get_tracer_provider", lambda: ProxyProvider()
    )
    monkeypatch.setattr(
        "opentelemetry.metrics.get_meter_provider", lambda: ProxyProvider()
    )
    monkeypatch.setattr(
        "opentelemetry._logs.get_logger_provider", lambda: ProxyProvider()
    )
    runtime = OpenTelemetryRuntime(
        settings, logger, service_name="demo", service_version="1.0"
    )

    with pytest.raises(RuntimeError, match=message):
        runtime.start()


@pytest.mark.parametrize(
    ("signal", "message"),
    [
        ("traces", "TracerProvider"),
        ("metrics", "MeterProvider"),
        ("logs", "LoggerProvider"),
    ],
)
def test_attach_mode_rejects_missing_provider(
    signal: str, message: str, logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ProxyProvider:
        pass

    settings = _settings(
        mode="attach",
        traces=signal == "traces",
        metrics=signal == "metrics",
        logs=signal == "logs",
    )
    monkeypatch.setattr(
        "opentelemetry.trace.get_tracer_provider", lambda: ProxyProvider()
    )
    monkeypatch.setattr(
        "opentelemetry.metrics.get_meter_provider", lambda: ProxyProvider()
    )
    monkeypatch.setattr(
        "opentelemetry._logs.get_logger_provider", lambda: ProxyProvider()
    )
    runtime = OpenTelemetryRuntime(
        settings, logger, service_name="demo", service_version="1.0"
    )

    with pytest.raises(RuntimeError, match=message):
        runtime.start()


def test_managed_mode_checks_and_sets_global_provider_slots(
    logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ProxyProvider:
        pass

    runtime = OpenTelemetryRuntime(
        _settings(traces=True, metrics=True, logs=True),
        logger,
        service_name="demo",
        service_version="1.0",
    )
    monkeypatch.setattr(
        "opentelemetry.trace.get_tracer_provider", lambda: ProxyProvider()
    )
    monkeypatch.setattr(
        "opentelemetry.metrics.get_meter_provider", lambda: ProxyProvider()
    )
    monkeypatch.setattr(
        "opentelemetry._logs.get_logger_provider", lambda: ProxyProvider()
    )
    runtime._assert_global_slots_available(runtime.settings)

    installed: dict[str, Any] = {}
    monkeypatch.setattr(
        "opentelemetry.trace.set_tracer_provider",
        lambda provider: installed.__setitem__("traces", provider),
    )
    monkeypatch.setattr(
        "opentelemetry.metrics.set_meter_provider",
        lambda provider: installed.__setitem__("metrics", provider),
    )
    monkeypatch.setattr(
        "opentelemetry._logs.set_logger_provider",
        lambda provider: installed.__setitem__("logs", provider),
    )
    providers = {name: object() for name in ("traces", "metrics", "logs")}
    runtime._set_global_providers(
        trace_provider=providers["traces"],
        meter_provider=providers["metrics"],
        logger_provider=providers["logs"],
    )

    assert installed == providers


def test_managed_mode_rejects_preinstalled_global_provider(
    logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = OpenTelemetryRuntime(
        _settings(), logger, service_name="demo", service_version="1.0"
    )
    monkeypatch.setattr("opentelemetry.trace.get_tracer_provider", RecordingProvider)

    with pytest.raises(RuntimeError, match="global existe deja"):
        runtime._assert_global_slots_available(runtime.settings)


def test_httpx_instrumentation_is_reference_counted(
    logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = RecordingProvider()
    events: list[tuple[str, dict[str, Any] | None]] = []
    monkeypatch.setattr(provider_module, "_HTTPX_REFERENCES", 0)
    monkeypatch.setattr("opentelemetry.trace.get_tracer_provider", lambda: provider)
    monkeypatch.setattr(
        "opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor.instrument",
        lambda self, **kwargs: events.append(("instrument", kwargs)),
    )
    monkeypatch.setattr(
        "opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor.uninstrument",
        lambda self: events.append(("uninstrument", None)),
    )
    settings = _settings(mode="external")
    settings.instrumentation.httpx = True
    runtimes = [
        OpenTelemetryRuntime(
            settings, logger, service_name="demo", service_version="1.0"
        )
        for _ in range(2)
    ]

    for runtime in runtimes:
        runtime.start()
    for runtime in runtimes:
        runtime.shutdown()

    assert [name for name, _ in events] == ["instrument", "uninstrument"]
    assert callable(events[0][1]["request_hook"])
    assert callable(events[0][1]["async_request_hook"])


def test_runtime_with_no_signals_starts_without_sdk_and_then_rejects_restart(
    logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = OpenTelemetryRuntime(
        _settings(traces=False, metrics=False, logs=False),
        logger,
        service_name="demo",
        service_version="1.0",
    )
    monkeypatch.setattr(
        runtime,
        "_require_sdk",
        lambda: pytest.fail("SDK should remain lazy when every signal is disabled"),
    )

    runtime.start()
    assert runtime.force_flush() is True
    runtime.shutdown()

    with pytest.raises(RuntimeError, match="ferme"):
        runtime.start()
    with pytest.raises(RuntimeError, match="traces"):
        runtime._require_trace_provider()
    with pytest.raises(RuntimeError, match="metrics"):
        runtime._require_meter_provider()


def test_require_sdk_reports_optional_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def without_sdk(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "opentelemetry.sdk":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_sdk)

    with pytest.raises(RuntimeError, match=r"arclith\[opentelemetry\]"):
        OpenTelemetryRuntime._require_sdk()


def test_force_flush_failure_modes_are_explicit(
    logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = OpenTelemetryRuntime(
        _settings(traces=False), logger, service_name="demo", service_version="1.0"
    )
    runtime.start()
    runtime._managed_state = provider_module._ManagedProviderState(
        "test", FailingProvider(), None, None
    )

    assert runtime.force_flush() is False

    runtime._resolved.failure_mode = "raise"
    with pytest.raises(ValueError, match="flush failed"):
        runtime.force_flush()


def test_fastapi_instrumentation_disabled_and_closed_paths(logger) -> None:
    settings = _settings(traces=False, metrics=False)
    runtime = OpenTelemetryRuntime(
        settings, logger, service_name="demo", service_version="1.0"
    )
    runtime.instrument_fastapi(FastAPI())
    runtime.shutdown()

    with pytest.raises(RuntimeError, match="ferme"):
        runtime.instrument_fastapi(FastAPI())
