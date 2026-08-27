from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from arclith.adapters.outbound.opentelemetry.propagation import (
    OpenTelemetryContextPropagator,
)
from arclith.adapters.outbound.opentelemetry.tracing import (
    OpenTelemetryTraceAdapter,
)
from arclith.infrastructure.config import (
    OpenTelemetryCaptureSettings,
    OpenTelemetryPropagationSettings,
)


def _adapter(
    provider: TracerProvider,
    *,
    capture: OpenTelemetryCaptureSettings | None = None,
) -> OpenTelemetryTraceAdapter:
    propagation = OpenTelemetryContextPropagator(OpenTelemetryPropagationSettings())
    return OpenTelemetryTraceAdapter(
        ensure_started=lambda: None,
        tracer_provider=lambda: provider,
        propagator=propagation,
        capture=capture or OpenTelemetryCaptureSettings(),
        enabled=lambda: True,
        flush=lambda timeout: True,
        shutdown=lambda timeout: None,
        diagnostics=lambda: {"backend": "opentelemetry"},
    )


def test_trace_adapter_exports_safe_attributes_without_payload_content() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = _adapter(provider)

    with tracer.span(
        "arclith.test",
        metadata={
            "operation.name": "test",
            "authorization": "Bearer secret",
            "request.body": "sensitive",
        },
    ) as span:
        span.set_outputs({"status": "success", "result": "sensitive"})

    exported = exporter.get_finished_spans()[0]
    assert exported.attributes["operation.name"] == "test"
    assert exported.attributes["arclith.output.status"] == "success"
    assert "authorization" not in exported.attributes
    assert "request.body" not in exported.attributes
    assert "arclith.output.result" not in exported.attributes


def test_trace_adapter_records_exception_and_error_status() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = _adapter(provider)

    try:
        with tracer.span("arclith.failure"):
            raise ValueError("sensitive detail")
    except ValueError:
        pass

    exported = exporter.get_finished_spans()[0]
    assert exported.status.is_ok is False
    assert exported.status.description == "ValueError"
    assert len(exported.events) == 1
    assert exported.events[0].name == "exception"


def test_trace_adapter_can_capture_tool_outputs_only_after_explicit_opt_in() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = _adapter(
        provider,
        capture=OpenTelemetryCaptureSettings(tool_content=True),
    )

    with tracer.span("arclith.tool") as span:
        span.set_outputs({"status": "success", "result": "explicit"})

    exported = exporter.get_finished_spans()[0]
    assert exported.attributes["arclith.output.result"] == "explicit"


def test_disabled_context_yields_no_span() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = _adapter(provider)

    with tracer.context(enabled=False):
        with tracer.span("ignored"):
            pass

    assert exporter.get_finished_spans() == ()
