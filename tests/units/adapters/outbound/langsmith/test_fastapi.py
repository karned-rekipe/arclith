from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from arclith.adapters.outbound.langsmith.fastapi import instrument_fastapi_app
from arclith.domain.ports.outbound.observability import TracePort, TraceSpan


class RecordingSpan(TraceSpan):
    def __init__(self) -> None:
        self.outputs: list[object | None] = []
        self.metadata: list[Mapping[str, object]] = []

    def set_outputs(self, outputs: object | None) -> None:
        self.outputs.append(outputs)

    def set_metadata(self, metadata: Mapping[str, object]) -> None:
        self.metadata.append(metadata)


class RecordingTracer(TracePort):
    def __init__(self) -> None:
        self.context_parents: list[Mapping[str, str] | None] = []
        self.spans: list[tuple[str, Mapping[str, object] | None, RecordingSpan]] = []

    @contextmanager
    def span(
        self,
        name: str,
        *,
        kind: str = "chain",
        inputs: object | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, object] | None = None,
    ) -> Iterator[TraceSpan]:
        span = RecordingSpan()
        self.spans.append((name, metadata, span))
        yield span

    @contextmanager
    def context(
        self,
        *,
        enabled: bool | None = None,
        project: str | None = None,
        tags: Sequence[str] = (),
        metadata: Mapping[str, object] | None = None,
        parent: Mapping[str, str] | None = None,
    ) -> Iterator[None]:
        self.context_parents.append(parent)
        yield

    def inject(self, headers: MutableMapping[str, str]) -> None:
        return None

    def flush(self, timeout: float | None = None) -> None:
        return None

    def close(self, timeout: float | None = None) -> None:
        return None


def test_fastapi_instrumentation_propagates_context_without_sensitive_headers() -> None:
    app = FastAPI()

    @app.get("/items/{item_id}")
    async def read_item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    tracer = RecordingTracer()
    instrument_fastapi_app(app, tracer)

    response = TestClient(app).get(
        "/items/42?token=secret",
        headers={
            "langsmith-trace": "trace-value",
            "traceparent": "00-trace-parent-01",
            "tracestate": "vendor=value",
            "baggage": "safe=yes",
            "authorization": "Bearer secret",
        },
    )

    assert response.status_code == 200
    assert tracer.context_parents == [
        {
            "langsmith-trace": "trace-value",
            "traceparent": "00-trace-parent-01",
            "tracestate": "vendor=value",
            "baggage": "safe=yes",
        }
    ]
    name, metadata, span = tracer.spans[0]
    assert name == "http.server.request"
    assert metadata == {"http.request.method": "GET", "url.scheme": "http"}
    assert span.outputs == [{"status_code": 200}]
    assert span.metadata == [
        {"http.response.status_code": 200, "http.route": "/items/{item_id}"}
    ]
