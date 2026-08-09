from typing import Any


type TraceMetadata = dict[str, str | bool]


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
    if not _valid_injected_id(trace_id) or not _valid_injected_id(span_id):
        return {}

    metadata: TraceMetadata = {
        "trace_id": trace_id,
        "span_id": span_id,
    }
    trace_sampled = getattr(record, "otelTraceSampled", None)
    if isinstance(trace_sampled, bool):
        metadata["trace_sampled"] = trace_sampled
    return metadata


def _valid_injected_id(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and any(char != "0" for char in value)
