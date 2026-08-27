from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI

from arclith.adapters.outbound.opentelemetry.config import (
    exporter_headers,
    resource_attributes_from_environment,
    resolve_export_endpoint,
    resolve_opentelemetry_settings,
)
from arclith.adapters.outbound.opentelemetry.fastapi import instrument_fastapi_app
from arclith.adapters.outbound.opentelemetry.resource import build_resource
from arclith.infrastructure.config import OpenTelemetrySettings


class RecordingRuntime:
    def __init__(self) -> None:
        self.apps: list[Any] = []

    def instrument_fastapi(self, app: Any) -> None:
        self.apps.append(app)


def test_fastapi_compatibility_entrypoint_delegates_to_runtime() -> None:
    app = FastAPI()
    runtime = RecordingRuntime()

    instrument_fastapi_app(app, runtime)  # type: ignore[arg-type]

    assert runtime.apps == [app]


def test_resolver_applies_override_then_environment_then_yaml() -> None:
    settings = OpenTelemetrySettings.model_validate(
        {
            "service": {"name": "yaml-service"},
            "export": {"endpoint": "http://yaml:4318"},
            "signals": {"traces": {"sampling_ratio": 0.25}},
        }
    )
    resolved = resolve_opentelemetry_settings(
        settings,
        service_name="fallback",
        service_version="1.2.3",
        environ={
            "OTEL_SERVICE_NAME": "env-service",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://env:4318",
            "OTEL_TRACES_SAMPLER_ARG": "0.5",
        },
        overrides={
            "service": {"name": "call-service"},
            "signals": {"traces": {"sampling_ratio": 0.75}},
        },
    )

    assert resolved.service.name == "call-service"
    assert resolved.service.version == "1.2.3"
    assert resolved.export.endpoint == "http://env:4318"
    assert resolved.signals.traces.sampling_ratio == 0.75


def test_resolver_honors_standard_sdk_disable_without_mutating_yaml() -> None:
    settings = OpenTelemetrySettings.model_validate(
        {
            "signals": {
                "traces": {"enabled": True},
                "metrics": {"enabled": True},
                "logs": {"enabled": True},
            }
        }
    )

    resolved = resolve_opentelemetry_settings(
        settings,
        service_name="demo",
        service_version="1.0",
        environ={"OTEL_SDK_DISABLED": "true"},
    )

    assert resolved.signals.traces.enabled is False
    assert resolved.signals.metrics.enabled is False
    assert resolved.signals.logs.enabled is False
    assert settings.signals.traces.enabled is True


def test_exporter_headers_use_signal_override_and_decode_values() -> None:
    settings = OpenTelemetrySettings()

    headers = exporter_headers(
        settings,
        "traces",
        {
            "OTEL_EXPORTER_OTLP_HEADERS": "authorization=base",
            "OTEL_EXPORTER_OTLP_TRACES_HEADERS": (
                "authorization=Bearer%20secret,x-tenant=demo"
            ),
        },
    )

    assert headers == {
        "authorization": "Bearer secret",
        "x-tenant": "demo",
    }


def test_resolve_endpoint_uses_signal_suffix_only_for_http() -> None:
    http = OpenTelemetrySettings.model_validate(
        {"export": {"endpoint": "http://collector:4318/"}}
    )
    grpc = OpenTelemetrySettings.model_validate(
        {
            "export": {
                "protocol": "grpc",
                "endpoint": "http://collector:4317/",
            }
        }
    )

    assert resolve_export_endpoint(http, "traces") == (
        "http://collector:4318/v1/traces"
    )
    assert resolve_export_endpoint(grpc, "traces") == "http://collector:4317"


def test_build_resource_has_service_identity_without_distro_claim(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_SERVICE_INSTANCE_ID", "pod-1")
    settings = OpenTelemetrySettings.model_validate(
        {
            "service": {
                "name": "demo",
                "namespace": "rekipe",
                "version": "1.2.3",
            },
            "resource": {
                "attributes": {"deployment.environment.name": "test"},
                "detectors": [],
            },
        }
    )

    resource = build_resource(settings)

    assert resource.attributes["service.name"] == "demo"
    assert resource.attributes["service.namespace"] == "rekipe"
    assert resource.attributes["service.version"] == "1.2.3"
    assert resource.attributes["service.instance.id"] == "pod-1"
    assert resource.attributes["deployment.environment.name"] == "test"
    assert not any(key.startswith("telemetry.distro.") for key in resource.attributes)


def test_resolver_supports_standard_signal_batch_limits_and_propagator_env() -> None:
    resolved = resolve_opentelemetry_settings(
        OpenTelemetrySettings(),
        service_name="demo",
        service_version="1.0",
        environ={
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://trace",
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "http://metric",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://log",
            "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
            "OTEL_EXPORTER_OTLP_COMPRESSION": "none",
            "OTEL_EXPORTER_OTLP_TIMEOUT": "2500",
            "OTEL_EXPORTER_OTLP_INSECURE": "true",
            "OTEL_TRACES_EXPORTER": "none",
            "OTEL_METRICS_EXPORTER": "otlp",
            "OTEL_LOGS_EXPORTER": "otlp",
            "OTEL_TRACES_SAMPLER": "always_on",
            "OTEL_METRIC_EXPORT_INTERVAL": "2000",
            "OTEL_METRIC_EXPORT_TIMEOUT": "1000",
            "OTEL_METRICS_EXEMPLAR_FILTER": "always_off",
            "OTEL_PROPAGATORS": "tracecontext,baggage",
            "OTEL_BSP_MAX_QUEUE_SIZE": "100",
            "OTEL_BSP_SCHEDULE_DELAY": "20",
            "OTEL_BSP_MAX_EXPORT_BATCH_SIZE": "50",
            "OTEL_BSP_EXPORT_TIMEOUT": "900",
            "OTEL_ATTRIBUTE_COUNT_LIMIT": "64",
            "OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT": "256",
            "OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT": "24",
            "OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT": "128",
            "OTEL_SPAN_EVENT_COUNT_LIMIT": "32",
            "OTEL_SPAN_LINK_COUNT_LIMIT": "16",
            "OTEL_RESOURCE_ATTRIBUTES": "release.revision=abc%20123,ignored",
        },
    )

    assert resolved.export.traces_endpoint == "http://trace"
    assert resolved.export.metrics_endpoint == "http://metric"
    assert resolved.export.logs_endpoint == "http://log"
    assert resolved.export.protocol == "grpc"
    assert resolved.export.compression == "none"
    assert resolved.export.timeout_millis == 2500
    assert resolved.export.insecure is True
    assert resolved.signals.traces.enabled is False
    assert resolved.signals.metrics.enabled is True
    assert resolved.signals.logs.enabled is True
    assert resolved.signals.metrics.export_interval_millis == 2000
    assert resolved.signals.metrics.exemplar_filter == "always_off"
    assert resolved.batch.max_queue_size == 100
    assert resolved.batch.max_export_batch_size == 50
    assert resolved.limits.attribute_count == 24
    assert resolved.limits.attribute_value_length == 128
    assert resolved.resource.attributes["release.revision"] == "abc 123"


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({"OTEL_SDK_DISABLED": "yes"}, "OTEL_SDK_DISABLED"),
        ({"OTEL_EXPORTER_OTLP_INSECURE": "sometimes"}, "INSECURE"),
        ({"OTEL_EXPORTER_OTLP_TIMEOUT": "slow"}, "doit etre un entier"),
        ({"OTEL_TRACES_SAMPLER_ARG": "many"}, "doit etre un nombre"),
        ({"OTEL_TRACES_EXPORTER": "console"}, "n'est pas supporte"),
    ],
)
def test_resolver_rejects_invalid_standard_environment(
    environ: dict[str, str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        resolve_opentelemetry_settings(
            OpenTelemetrySettings(),
            service_name="demo",
            service_version="1.0",
            environ=environ,
        )


def test_resource_and_header_parsers_ignore_empty_or_malformed_values() -> None:
    assert resource_attributes_from_environment({}) == {}
    assert resource_attributes_from_environment(
        {"OTEL_RESOURCE_ATTRIBUTES": "safe=ok,malformed"}
    ) == {"safe": "ok"}
    assert exporter_headers(OpenTelemetrySettings(), "logs", {}) is None
