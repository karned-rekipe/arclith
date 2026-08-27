from collections.abc import Mapping
from typing import Any, Callable

from arclith.domain.ports.outbound.observability import CorrelationContextPort


type TraceMetadata = dict[str, str | bool]
_HEX_DIGITS = frozenset("0123456789abcdef")


def current_trace_metadata() -> TraceMetadata:
    try:
        from opentelemetry.trace import get_current_span
    except ImportError:
        return {}

    context = get_current_span().get_span_context()
    if not context.is_valid:
        return {}

    return {
        "trace_id": format(context.trace_id, "032x"),
        "span_id": format(context.span_id, "016x"),
        "trace_sampled": context.trace_flags.sampled,
    }


def log_record_trace_metadata(record: Any) -> TraceMetadata:
    trace_id = getattr(record, "otelTraceID", "")
    span_id = getattr(record, "otelSpanID", "")
    if not _valid_injected_id(trace_id, expected_length=32) or not _valid_injected_id(
        span_id,
        expected_length=16,
    ):
        return {}

    metadata: TraceMetadata = {
        "trace_id": trace_id,
        "span_id": span_id,
    }
    trace_sampled = getattr(record, "otelTraceSampled", None)
    if isinstance(trace_sampled, bool):
        metadata["trace_sampled"] = trace_sampled
    return metadata


def _valid_injected_id(value: Any, *, expected_length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == expected_length
        and any(char != "0" for char in value)
        and all(char.lower() in _HEX_DIGITS for char in value)
    )


class OpenTelemetryCorrelationContext(CorrelationContextPort):
    def __init__(self, enabled: Callable[[], bool] | None = None) -> None:
        self._enabled = enabled or (lambda: True)

    def current(self) -> Mapping[str, str | bool]:
        if not self._enabled():
            return {}
        return current_trace_metadata()

    def from_log_record(self, record: Any) -> Mapping[str, str | bool]:
        if not self._enabled():
            return {}
        return log_record_trace_metadata(record)
