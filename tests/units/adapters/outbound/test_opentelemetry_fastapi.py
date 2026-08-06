from fastapi import FastAPI

from arclith.adapters.outbound.opentelemetry.fastapi import (
    _configure_opentelemetry,
    _headers_from_env,
    _resolve_endpoint,
    instrument_fastapi_app,
)
from arclith.infrastructure.config import OpenTelemetrySettings


def test_instrument_fastapi_app_returns_when_disabled() -> None:
    settings = OpenTelemetrySettings(enabled=False)

    instrument_fastapi_app(FastAPI(), settings, service_name="demo", service_version="1.0.0")


def test_configure_opentelemetry_skips_when_exports_disabled() -> None:
    settings = OpenTelemetrySettings(traces=False, metrics=False)

    _configure_opentelemetry(settings, service_name="demo", service_version="1.0.0")


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
