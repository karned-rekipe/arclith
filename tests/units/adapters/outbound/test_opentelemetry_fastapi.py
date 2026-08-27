from fastapi import FastAPI

from arclith.adapters.outbound.opentelemetry.fastapi import (
    _build_resource,
    _headers_from_env,
    _instrument_logging_correlation,
    _resolve_endpoint,
    configure_opentelemetry,
    instrument_fastapi_app,
)
from arclith.infrastructure.config import OpenTelemetrySettings


def test_instrument_fastapi_app_returns_when_exports_disabled() -> None:
    settings = OpenTelemetrySettings(traces=False, metrics=False)

    instrument_fastapi_app(FastAPI(), settings, service_name="demo", service_version="1.0.0")


def test_configure_opentelemetry_skips_when_exports_disabled() -> None:
    settings = OpenTelemetrySettings(traces=False, metrics=False)

    configure_opentelemetry(settings, service_name="demo", service_version="1.0.0")


def test_build_resource_adds_service_identity_and_environment(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment.name=local")

    resource = _build_resource(
        OpenTelemetrySettings(service_name="configured-service"),
        service_name="fallback-service",
        service_version="1.2.3",
    )

    assert resource.attributes["service.name"] == "configured-service"
    assert resource.attributes["service.version"] == "1.2.3"
    assert resource.attributes["deployment.environment.name"] == "local"


def test_instrument_logging_correlation_injects_trace_context(monkeypatch) -> None:
    calls: list[dict[str, bool]] = []

    class FakeLoggingInstrumentor:
        def instrument(self, **kwargs: bool) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(
        "opentelemetry.instrumentation.logging.LoggingInstrumentor",
        FakeLoggingInstrumentor,
    )

    _instrument_logging_correlation()

    assert calls == [{"set_logging_format": False, "inject_trace_context": True}]


def test_resolve_endpoint_uses_explicit_value() -> None:
    assert _resolve_endpoint("http://collector:4318/custom", "http://ignored:4318", "v1/traces") == (
        "http://collector:4318/custom"
    )


def test_resolve_endpoint_adds_http_suffix() -> None:
    assert _resolve_endpoint(None, "http://collector:4318/", "v1/traces") == "http://collector:4318/v1/traces"


def test_resolve_endpoint_keeps_grpc_base() -> None:
    assert _resolve_endpoint(None, "http://collector:4317") == "http://collector:4317"


def test_headers_from_env_ignores_missing_env(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_TEST_HEADERS", raising=False)

    assert _headers_from_env("OTEL_TEST_HEADERS") is None


def test_headers_from_env_parses_valid_pairs(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_TEST_HEADERS", "authorization=Bearer test,x-tenant=demo,ignored")

    assert _headers_from_env("OTEL_TEST_HEADERS") == {
        "authorization": "Bearer test",
        "x-tenant": "demo",
    }
