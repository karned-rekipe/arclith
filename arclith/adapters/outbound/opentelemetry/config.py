from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote

from arclith.infrastructure.config import OpenTelemetrySettings


def resolve_opentelemetry_settings(
    settings: OpenTelemetrySettings,
    *,
    service_name: str,
    service_version: str,
    overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> OpenTelemetrySettings:
    """Resolve explicit overrides > OTEL_* > YAML > model defaults."""

    env = os.environ if environ is None else environ
    data = settings.model_dump(mode="python")
    _apply_environment(data, env)
    if overrides:
        _deep_update(data, overrides)
    resolved = OpenTelemetrySettings.model_validate(data)
    if not (resolved.service.name or service_name).strip():
        raise ValueError("OpenTelemetry requiert un service.name non vide")
    resolved.service.name = resolved.service.name or service_name
    resolved.service.version = resolved.service.version or service_version
    return resolved


def resource_attributes_from_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = os.environ if environ is None else environ
    raw = env.get("OTEL_RESOURCE_ATTRIBUTES", "").strip()
    if not raw:
        return {}
    attributes: dict[str, str] = {}
    for item in raw.split(","):
        key, separator, value = item.partition("=")
        key = key.strip()
        if separator and key:
            attributes[key] = unquote(value.strip())
    return attributes


def exporter_headers(
    settings: OpenTelemetrySettings,
    signal: str,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str] | None:
    env = os.environ if environ is None else environ
    signal_name = f"OTEL_EXPORTER_OTLP_{signal.upper()}_HEADERS"
    raw = env.get(signal_name, env.get(settings.export.headers_env, "")).strip()
    if not raw:
        return None
    headers: dict[str, str] = {}
    for item in raw.split(","):
        key, separator, value = item.partition("=")
        key = key.strip()
        if separator and key:
            headers[key] = unquote(value.strip())
    return headers or None


def resolve_export_endpoint(
    settings: OpenTelemetrySettings,
    signal: str,
) -> str:
    explicit = getattr(settings.export, f"{signal}_endpoint")
    if explicit:
        return explicit
    endpoint = settings.export.endpoint.rstrip("/")
    if settings.export.protocol == "grpc":
        return endpoint
    return f"{endpoint}/v1/{signal}"


def _apply_environment(data: dict[str, Any], env: Mapping[str, str]) -> None:
    service = data["service"]
    export = data["export"]
    signals = data["signals"]
    propagation = data["propagation"]
    batch = data["batch"]
    limits = data["limits"]

    _set_string(env, "OTEL_SERVICE_NAME", service, "name")
    _set_string(env, "OTEL_EXPORTER_OTLP_ENDPOINT", export, "endpoint")
    _set_string(env, "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", export, "traces_endpoint")
    _set_string(env, "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", export, "metrics_endpoint")
    _set_string(env, "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", export, "logs_endpoint")
    _set_string(env, "OTEL_EXPORTER_OTLP_PROTOCOL", export, "protocol")
    _set_string(env, "OTEL_EXPORTER_OTLP_COMPRESSION", export, "compression")
    _set_int(env, "OTEL_EXPORTER_OTLP_TIMEOUT", export, "timeout_millis")
    _set_bool(env, "OTEL_EXPORTER_OTLP_INSECURE", export, "insecure")

    if _env_bool(env, "OTEL_SDK_DISABLED") is True:
        for signal in ("traces", "metrics", "logs"):
            signals[signal]["enabled"] = False
    for signal, variable in (
        ("traces", "OTEL_TRACES_EXPORTER"),
        ("metrics", "OTEL_METRICS_EXPORTER"),
        ("logs", "OTEL_LOGS_EXPORTER"),
    ):
        exporter = env.get(variable, "").strip().lower()
        if exporter:
            if exporter not in {"none", "otlp"}:
                raise ValueError(
                    f"{variable}={exporter!r} n'est pas supporte; utilisez otlp ou none"
                )
            signals[signal]["enabled"] = exporter == "otlp"

    _set_string(env, "OTEL_TRACES_SAMPLER", signals["traces"], "sampler")
    _set_float(
        env,
        "OTEL_TRACES_SAMPLER_ARG",
        signals["traces"],
        "sampling_ratio",
    )
    _set_int(
        env,
        "OTEL_METRIC_EXPORT_INTERVAL",
        signals["metrics"],
        "export_interval_millis",
    )
    _set_int(
        env,
        "OTEL_METRIC_EXPORT_TIMEOUT",
        signals["metrics"],
        "export_timeout_millis",
    )
    _set_string(
        env,
        "OTEL_METRICS_EXEMPLAR_FILTER",
        signals["metrics"],
        "exemplar_filter",
    )
    propagators = env.get("OTEL_PROPAGATORS", "").strip()
    if propagators:
        propagation["propagators"] = [
            value.strip().lower()
            for value in propagators.split(",")
            if value.strip().lower() != "none"
        ]

    _set_int(env, "OTEL_BSP_MAX_QUEUE_SIZE", batch, "max_queue_size")
    _set_int(env, "OTEL_BSP_SCHEDULE_DELAY", batch, "schedule_delay_millis")
    _set_int(
        env,
        "OTEL_BSP_MAX_EXPORT_BATCH_SIZE",
        batch,
        "max_export_batch_size",
    )
    _set_int(env, "OTEL_BSP_EXPORT_TIMEOUT", batch, "export_timeout_millis")
    _set_int(env, "OTEL_ATTRIBUTE_COUNT_LIMIT", limits, "attribute_count")
    _set_int(
        env,
        "OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT",
        limits,
        "attribute_value_length",
    )
    _set_int(env, "OTEL_SPAN_EVENT_COUNT_LIMIT", limits, "span_event_count")
    _set_int(env, "OTEL_SPAN_LINK_COUNT_LIMIT", limits, "span_link_count")
    _set_int(env, "OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT", limits, "attribute_count")
    _set_int(
        env,
        "OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT",
        limits,
        "attribute_value_length",
    )

    resource = data["resource"]
    resource["attributes"] = {
        **resource.get("attributes", {}),
        **resource_attributes_from_environment(env),
    }


def _deep_update(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


def _set_string(
    env: Mapping[str, str], variable: str, target: dict[str, Any], key: str
) -> None:
    value = env.get(variable, "").strip()
    if value:
        target[key] = value


def _set_int(
    env: Mapping[str, str], variable: str, target: dict[str, Any], key: str
) -> None:
    value = env.get(variable, "").strip()
    if not value:
        return
    try:
        target[key] = int(value)
    except ValueError as exc:
        raise ValueError(f"{variable} doit etre un entier") from exc


def _set_float(
    env: Mapping[str, str], variable: str, target: dict[str, Any], key: str
) -> None:
    value = env.get(variable, "").strip()
    if not value:
        return
    try:
        target[key] = float(value)
    except ValueError as exc:
        raise ValueError(f"{variable} doit etre un nombre") from exc


def _set_bool(
    env: Mapping[str, str], variable: str, target: dict[str, Any], key: str
) -> None:
    value = _env_bool(env, variable)
    if value is not None:
        target[key] = value


def _env_bool(env: Mapping[str, str], variable: str) -> bool | None:
    value = env.get(variable, "").strip().lower()
    if not value:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"{variable} doit valoir true ou false")
