import urllib.parse

from arclith.adapters.outbound.langsmith.propagation import (
    filter_baggage,
    merge_baggage,
    normalized_parent_headers,
)


def test_filter_baggage_keeps_only_allowlisted_metadata_and_fields() -> None:
    metadata = urllib.parse.quote('{"safe":"yes","secret":"no"}')
    baggage = (
        f"langsmith-metadata={metadata},langsmith-tags=dev,"
        "langsmith-project=agent-tests,correlation.id=corr-1,token=secret"
    )

    filtered = filter_baggage(
        baggage,
        allowlist={"safe", "tags", "project", "correlation.id"},
    )

    assert "safe" in urllib.parse.unquote(filtered)
    assert "secret" not in urllib.parse.unquote(filtered)
    assert "langsmith-tags=dev" in filtered
    assert "langsmith-project=agent-tests" in filtered
    assert "correlation.id=corr-1" in filtered
    assert "token=" not in filtered


def test_filter_baggage_rejects_invalid_or_unallowed_values() -> None:
    assert filter_baggage("", allowlist={"safe"}) == ""
    assert filter_baggage("safe=value", allowlist=set()) == ""
    assert (
        filter_baggage("invalid,langsmith-metadata=not-json", allowlist={"safe"}) == ""
    )


def test_normalized_parent_headers_filters_transport_headers() -> None:
    headers = normalized_parent_headers(
        {
            "LangSmith-Trace": "trace-value",
            "TraceParent": "00-abc-def-01",
            "TraceState": "vendor=value",
            "Baggage": "safe=yes,secret=no",
            "Authorization": "Bearer secret",
        },
        allowlist={"safe"},
        langsmith_headers=True,
        traceparent=True,
    )

    assert headers == {
        "langsmith-trace": "trace-value",
        "traceparent": "00-abc-def-01",
        "tracestate": "vendor=value",
        "baggage": "safe=yes",
    }
    assert (
        normalized_parent_headers(
            None,
            allowlist=set(),
            langsmith_headers=True,
            traceparent=True,
        )
        == {}
    )


def test_merge_baggage_is_stable_and_deduplicated() -> None:
    assert merge_baggage("a=1,b=2", "b=3,c=4") == "a=1,b=2,c=4"
