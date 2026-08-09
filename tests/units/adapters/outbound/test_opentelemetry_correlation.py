from types import SimpleNamespace

from arclith.adapters.outbound.opentelemetry.correlation import log_record_trace_metadata


def test_log_record_trace_metadata_reads_injected_trace_ids() -> None:
    record = SimpleNamespace(
        otelTraceID="0" * 31 + "1",
        otelSpanID="0" * 15 + "2",
        otelTraceSampled=True,
    )

    assert log_record_trace_metadata(record) == {
        "trace_id": "0" * 31 + "1",
        "span_id": "0" * 15 + "2",
        "trace_sampled": True,
    }


def test_log_record_trace_metadata_ignores_missing_span_context() -> None:
    record = SimpleNamespace(otelTraceID="0", otelSpanID="0", otelTraceSampled=False)

    assert log_record_trace_metadata(record) == {}


def test_log_record_trace_metadata_ignores_zero_padded_span_context() -> None:
    record = SimpleNamespace(otelTraceID="0" * 32, otelSpanID="0" * 16, otelTraceSampled=False)

    assert log_record_trace_metadata(record) == {}


def test_log_record_trace_metadata_ignores_malformed_trace_ids() -> None:
    record = SimpleNamespace(
        otelTraceID="0" * 31 + "z",
        otelSpanID="0" * 15 + "2",
        otelTraceSampled=True,
    )

    assert log_record_trace_metadata(record) == {}


def test_log_record_trace_metadata_ignores_wrong_length_span_ids() -> None:
    record = SimpleNamespace(
        otelTraceID="0" * 31 + "1",
        otelSpanID="0" * 16 + "2",
        otelTraceSampled=True,
    )

    assert log_record_trace_metadata(record) == {}
