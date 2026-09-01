from __future__ import annotations

from opentelemetry import baggage, context
from opentelemetry.sdk.trace import TracerProvider

from arclith.adapters.outbound.opentelemetry.propagation import (
    OpenTelemetryContextPropagator,
    _filter_baggage,
)
from arclith.infrastructure.config import OpenTelemetryPropagationSettings


def test_baggage_filter_keeps_only_allowlisted_bounded_members() -> None:
    filtered = _filter_baggage(
        "safe=ok,secret=hidden,other=value",
        allowlist={"safe", "other"},
        max_bytes=14,
    )

    assert filtered == "safe=ok"


def test_propagator_injects_trace_context_and_allowlisted_baggage() -> None:
    provider = TracerProvider()
    tracer = provider.get_tracer("test")
    propagator = OpenTelemetryContextPropagator(
        OpenTelemetryPropagationSettings(baggage_allowlist=["safe"])
    )
    baggage_context = baggage.set_baggage("safe", "ok")
    baggage_context = baggage.set_baggage("secret", "hidden", baggage_context)
    token = context.attach(baggage_context)
    try:
        with tracer.start_as_current_span("producer"):
            carrier: dict[str, str] = {}
            propagator.inject(carrier)
    finally:
        context.detach(token)

    assert carrier["traceparent"].startswith("00-")
    assert carrier["baggage"] == "safe=ok"


def test_propagator_attaches_and_detaches_incoming_context() -> None:
    provider = TracerProvider()
    tracer = provider.get_tracer("test")
    propagator = OpenTelemetryContextPropagator(OpenTelemetryPropagationSettings())
    with tracer.start_as_current_span("producer") as producer:
        carrier: dict[str, str] = {}
        propagator.inject(carrier)
    expected_trace_id = producer.get_span_context().trace_id

    with propagator.context(carrier):
        with tracer.start_as_current_span("consumer") as consumer:
            assert consumer.get_span_context().trace_id == expected_trace_id

    with tracer.start_as_current_span("independent") as independent:
        assert independent.get_span_context().trace_id != expected_trace_id


def test_propagator_extracts_only_normalized_safe_headers() -> None:
    propagator = OpenTelemetryContextPropagator(
        OpenTelemetryPropagationSettings(baggage_allowlist=["safe"])
    )

    assert propagator.extract(
        {
            "TraceParent": "00-trace-parent-01",
            "TraceState": "vendor=value",
            "Baggage": "safe=yes,secret=no",
            "Authorization": "Bearer sensitive",
            "Cookie": "session=sensitive",
        }
    ) == {
        "traceparent": "00-trace-parent-01",
        "tracestate": "vendor=value",
        "baggage": "safe=yes",
    }

    disabled = OpenTelemetryContextPropagator(
        OpenTelemetryPropagationSettings(
            propagators=[],
            baggage_allowlist=["safe"],
        )
    )
    assert (
        disabled.extract({"traceparent": "00-trace-parent-01", "baggage": "safe=yes"})
        == {}
    )
