from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from arclith.infrastructure.settings._base import SettingsModel


class OpenTelemetryServiceSettings(SettingsModel):
    name: str | None = None
    namespace: str | None = None
    version: str | None = None
    instance_id_env: str = "OTEL_SERVICE_INSTANCE_ID"


def _default_resource_detectors() -> list[Literal["env", "process", "host"]]:
    return ["env", "process", "host"]


class OpenTelemetryResourceSettings(SettingsModel):
    attributes: dict[str, str | bool | int | float] = Field(default_factory=dict)
    detectors: list[Literal["env", "process", "host"]] = Field(
        default_factory=_default_resource_detectors
    )


class OpenTelemetryExportSettings(SettingsModel):
    protocol: Literal["http/protobuf", "grpc"] = "http/protobuf"
    endpoint: str = "http://localhost:4318"
    traces_endpoint: str | None = None
    metrics_endpoint: str | None = None
    logs_endpoint: str | None = None
    headers_env: str = "OTEL_EXPORTER_OTLP_HEADERS"
    compression: Literal["gzip", "none"] = "gzip"
    timeout_millis: int = 10000
    insecure: bool = False

    @field_validator("endpoint", "headers_env")
    @classmethod
    def must_not_be_blank(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("la valeur ne doit pas etre vide")
        return value

    @field_validator("timeout_millis")
    @classmethod
    def must_have_positive_timeout(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("timeout_millis doit etre > 0")
        return v


class OpenTelemetryTracesSettings(SettingsModel):
    enabled: bool = True
    sampler: Literal[
        "always_on",
        "always_off",
        "traceidratio",
        "parentbased_always_on",
        "parentbased_always_off",
        "parentbased_traceidratio",
    ] = "parentbased_traceidratio"
    sampling_ratio: float = 0.1

    @field_validator("sampling_ratio")
    @classmethod
    def must_have_valid_sampling_ratio(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("sampling_ratio doit etre compris entre 0.0 et 1.0")
        return v


class OpenTelemetryMetricsSettings(SettingsModel):
    enabled: bool = False
    export_interval_millis: int = 60000
    export_timeout_millis: int = 30000
    exemplar_filter: Literal["always_on", "always_off", "trace_based"] = "trace_based"

    @field_validator("export_interval_millis", "export_timeout_millis")
    @classmethod
    def must_be_positive_interval(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("les intervalles metriques doivent etre > 0")
        return v


class OpenTelemetryLogsSettings(SettingsModel):
    enabled: bool = False
    correlate: bool = True


class OpenTelemetrySignalsSettings(SettingsModel):
    traces: OpenTelemetryTracesSettings = Field(
        default_factory=OpenTelemetryTracesSettings
    )
    metrics: OpenTelemetryMetricsSettings = Field(
        default_factory=OpenTelemetryMetricsSettings
    )
    logs: OpenTelemetryLogsSettings = Field(default_factory=OpenTelemetryLogsSettings)


def _default_propagators() -> list[Literal["tracecontext", "baggage"]]:
    return ["tracecontext", "baggage"]


_LEGACY_OPENTELEMETRY_KEYS = {
    "service_name",
    "endpoint",
    "traces_endpoint",
    "metrics_endpoint",
    "protocol",
    "headers_env",
    "traces",
    "metrics",
    "instrument_fastapi",
    "metrics_export_interval_millis",
}


def _move_legacy_values(
    source: dict[str, Any],
    target: dict[str, Any],
    mapping: dict[str, str],
) -> None:
    for old_name, new_name in mapping.items():
        if old_name in source:
            target.setdefault(new_name, source.pop(old_name))


def _migrate_legacy_opentelemetry(data: dict[str, Any]) -> dict[str, Any]:
    service = dict(data.get("service") or {})
    export = dict(data.get("export") or {})
    signals = dict(data.get("signals") or {})
    traces = dict(signals.get("traces") or {})
    metrics = dict(signals.get("metrics") or {})
    instrumentation = dict(data.get("instrumentation") or {})
    _move_legacy_values(data, service, {"service_name": "name"})
    _move_legacy_values(
        data,
        export,
        {
            name: name
            for name in (
                "endpoint",
                "traces_endpoint",
                "metrics_endpoint",
                "protocol",
                "headers_env",
            )
        },
    )
    _move_legacy_values(data, traces, {"traces": "enabled"})
    _move_legacy_values(
        data,
        metrics,
        {
            "metrics": "enabled",
            "metrics_export_interval_millis": "export_interval_millis",
        },
    )
    _move_legacy_values(data, instrumentation, {"instrument_fastapi": "fastapi"})
    signals.update({"traces": traces, "metrics": metrics})
    data.update(
        {
            "service": service,
            "export": export,
            "signals": signals,
            "instrumentation": instrumentation,
        }
    )
    return data


class OpenTelemetryPropagationSettings(SettingsModel):
    propagators: list[Literal["tracecontext", "baggage"]] = Field(
        default_factory=_default_propagators
    )
    baggage_allowlist: list[str] = Field(default_factory=list)
    max_baggage_bytes: int = 8192

    @field_validator("propagators", "baggage_allowlist")
    @classmethod
    def must_not_have_duplicates(cls, v: list[str]) -> list[str]:
        if len(v) != len(set(v)):
            raise ValueError("la liste ne doit pas contenir de doublons")
        return v

    @field_validator("max_baggage_bytes")
    @classmethod
    def must_have_positive_baggage_limit(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("max_baggage_bytes doit etre > 0")
        return v


class OpenTelemetryInstrumentationSettings(SettingsModel):
    fastapi: bool = True
    httpx: bool = True
    fastmcp: bool = True
    rabbitmq: bool = True
    pydantic_ai: bool = True
    langgraph: bool = True
    repositories: bool = False
    caches: bool = False
    excluded_urls: list[str] = Field(
        default_factory=lambda: ["/health", "/ready", "/metrics"]
    )


class OpenTelemetryCaptureSettings(SettingsModel):
    request_headers_allowlist: list[str] = Field(default_factory=list)
    response_headers_allowlist: list[str] = Field(default_factory=list)
    genai_content: bool = False
    tool_content: bool = False
    db_statement: bool = False


class OpenTelemetryBatchSettings(SettingsModel):
    max_queue_size: int = 2048
    schedule_delay_millis: int = 5000
    max_export_batch_size: int = 512
    export_timeout_millis: int = 30000

    @field_validator(
        "max_queue_size",
        "schedule_delay_millis",
        "max_export_batch_size",
        "export_timeout_millis",
    )
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("les reglages batch doivent etre > 0")
        return v

    @model_validator(mode="after")
    def validate_batch_size(self) -> "OpenTelemetryBatchSettings":
        if self.max_export_batch_size > self.max_queue_size:
            raise ValueError("max_export_batch_size doit etre <= max_queue_size")
        return self


class OpenTelemetryLimitsSettings(SettingsModel):
    attribute_count: int = 128
    attribute_value_length: int = 4096
    span_event_count: int = 128
    span_link_count: int = 128

    @field_validator(
        "attribute_count",
        "attribute_value_length",
        "span_event_count",
        "span_link_count",
    )
    @classmethod
    def must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("les limites doivent etre >= 0")
        return v


class OpenTelemetrySettings(SettingsModel):
    mode: Literal["managed", "attach", "external"] = "managed"
    service: OpenTelemetryServiceSettings = Field(
        default_factory=OpenTelemetryServiceSettings
    )
    resource: OpenTelemetryResourceSettings = Field(
        default_factory=OpenTelemetryResourceSettings
    )
    export: OpenTelemetryExportSettings = Field(
        default_factory=OpenTelemetryExportSettings
    )
    signals: OpenTelemetrySignalsSettings = Field(
        default_factory=OpenTelemetrySignalsSettings
    )
    propagation: OpenTelemetryPropagationSettings = Field(
        default_factory=OpenTelemetryPropagationSettings
    )
    instrumentation: OpenTelemetryInstrumentationSettings = Field(
        default_factory=OpenTelemetryInstrumentationSettings
    )
    capture: OpenTelemetryCaptureSettings = Field(
        default_factory=OpenTelemetryCaptureSettings
    )
    batch: OpenTelemetryBatchSettings = Field(
        default_factory=OpenTelemetryBatchSettings
    )
    limits: OpenTelemetryLimitsSettings = Field(
        default_factory=OpenTelemetryLimitsSettings
    )
    flush_timeout_seconds: float = 5.0
    failure_mode: Literal["log-and-continue", "raise"] = "log-and-continue"

    @model_validator(mode="before")
    @classmethod
    def migrate_flat_configuration(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if not _LEGACY_OPENTELEMETRY_KEYS.intersection(data):
            return data
        return _migrate_legacy_opentelemetry(data)

    @field_validator("flush_timeout_seconds")
    @classmethod
    def must_have_positive_flush_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("flush_timeout_seconds doit etre > 0")
        return v

    # Compatibility accessors for projects generated before the nested runtime config.
    @property
    def service_name(self) -> str | None:
        return self.service.name

    @property
    def endpoint(self) -> str:
        return self.export.endpoint

    @property
    def traces_endpoint(self) -> str | None:
        return self.export.traces_endpoint

    @property
    def metrics_endpoint(self) -> str | None:
        return self.export.metrics_endpoint

    @property
    def protocol(self) -> Literal["http/protobuf", "grpc"]:
        return self.export.protocol

    @property
    def headers_env(self) -> str:
        return self.export.headers_env

    @property
    def traces(self) -> bool:
        return self.signals.traces.enabled

    @property
    def metrics(self) -> bool:
        return self.signals.metrics.enabled

    @property
    def instrument_fastapi(self) -> bool:
        return self.instrumentation.fastapi

    @property
    def metrics_export_interval_millis(self) -> int:
        return self.signals.metrics.export_interval_millis
