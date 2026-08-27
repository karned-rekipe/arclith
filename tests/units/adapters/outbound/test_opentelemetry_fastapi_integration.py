from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from arclith.adapters.outbound.opentelemetry.runtime import OpenTelemetryRuntime
from arclith.infrastructure.config import OpenTelemetrySettings


def test_fastapi_emits_route_and_error_spans_without_query_or_probe(
    logger, monkeypatch
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr("opentelemetry.trace.get_tracer_provider", lambda: provider)
    settings = OpenTelemetrySettings.model_validate(
        {
            "mode": "external",
            "signals": {
                "traces": {"enabled": True, "sampler": "always_on"},
                "metrics": {"enabled": False},
                "logs": {"enabled": False},
            },
            "instrumentation": {"fastapi": True, "httpx": False},
        }
    )
    runtime = OpenTelemetryRuntime(
        settings, logger, service_name="test-api", service_version="1.0"
    )
    app = FastAPI()

    @app.get("/items/{item_id}")
    def item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    @app.get("/boom")
    def boom() -> None:
        raise ValueError("private failure detail")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    runtime.instrument_fastapi(app)
    runtime.start()
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/items/42?token=secret&search=private").status_code == 200
        assert client.get("/boom").status_code == 500
        assert client.get("/health").status_code == 200

    spans = exporter.get_finished_spans()
    server_spans = [span for span in spans if span.kind.name == "SERVER"]
    routes = {span.attributes.get("http.route") for span in server_spans}
    rendered = repr([span.attributes for span in server_spans])

    assert routes == {"/items/{item_id}", "/boom"}
    assert "secret" not in rendered
    assert "private" not in rendered
    assert "/health" not in routes
    failed = next(
        span for span in server_spans if span.attributes["http.route"] == "/boom"
    )
    assert failed.status.status_code.name == "ERROR"
    assert any(event.name == "exception" for event in failed.events)

    runtime.shutdown()
    provider.shutdown()
