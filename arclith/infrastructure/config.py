from __future__ import annotations

from pathlib import Path

import yaml

from arclith.infrastructure.settings import (  # noqa: F401
    AdaptersSettings,
    ApiSettings,
    AppConfig,
    AppSettings,
    CacheControlSettings,
    CacheSettings,
    CommandBusAdapter,
    CommandBusSettings,
    DuckDBSettings,
    EmbeddingAdapter,
    EmbeddingSettings,
    ETagSettings,
    HttpSettings,
    IdempotencySettings,
    KeycloakSettings,
    LangGraphCheckpointerSettings,
    LangGraphPersistenceSettings,
    LangGraphSemanticSearchSettings,
    LangGraphSettings,
    LangGraphStoreSettings,
    LangGraphStreamMode,
    LangSmithCaptureSettings,
    LangSmithDiagnosticsSettings,
    LangSmithInstrumentationSettings,
    LangSmithLifecycleSettings,
    LangSmithPropagationSettings,
    LangSmithSettings,
    LangSmithTracingSettings,
    LicenseSettings,
    LMSettings,
    MariaDBSettings,
    McpSettings,
    MongoDBSettings,
    ObservabilityAdapter,
    ObservabilitySettings,
    OpenTelemetryBatchSettings,
    OpenTelemetryCaptureSettings,
    OpenTelemetryExportSettings,
    OpenTelemetryInstrumentationSettings,
    OpenTelemetryLimitsSettings,
    OpenTelemetryLogsSettings,
    OpenTelemetryMetricsSettings,
    OpenTelemetryPropagationSettings,
    OpenTelemetryResourceSettings,
    OpenTelemetryServiceSettings,
    OpenTelemetrySettings,
    OpenTelemetrySignalsSettings,
    OpenTelemetryTracesSettings,
    PostgreSQLSettings,
    ProbeSettings,
    RabbitMQCommandBusSettings,
    SoftDeleteSettings,
    StorageAdapter,
    StorageSettings,
    TenantSettings,
    VectorDistance,
    VectorStoreAdapter,
    VectorStoreSettings,
)

_INBOUND_ALIAS: dict[str, str] = {"fastapi": "api", "fastmcp": "mcp"}


def _resolve_key_path(rel: Path) -> list[str]:
    """Derive AppConfig injection key path from a relative file path inside config/.

    Convention:
      config/app.yaml                      → ["app"]
      config/soft_delete.yaml              → ["soft_delete"]
      config/adapters/adapters.yaml        → ["adapters"]
      config/adapters/outbound/<name>.yaml → ["adapters", "<name>"]
      config/adapters/inbound/<name>.yaml  → ["<alias>"] or ["<name>"]
      config/<name>.yaml                   → ["<name>"]
    """
    parts = rel.with_suffix("").parts

    # Single level: config/<name>.yaml → ["<name>"]
    if len(parts) == 1:
        return [parts[0]]

    # Two levels: config/adapters/adapters.yaml → ["adapters"]
    if len(parts) == 2:
        if parts[0] == "adapters" and parts[1] == "adapters":
            return ["adapters"]
        return []

    # Three levels: config/adapters/{outbound|inbound}/<name>.yaml
    if len(parts) == 3 and parts[0] == "adapters":
        if parts[1] == "outbound":
            return ["adapters", parts[2]]
        if parts[1] == "inbound":
            return [_INBOUND_ALIAS.get(parts[2], parts[2])]

    return []


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _wrap_at_path(key_path: list[str], value: dict) -> dict:
    result: dict = value
    for key in reversed(key_path):
        result = {key: result}
    return result


def _build_merged_dict(config_dir: Path) -> dict:
    """Walk a config/ directory and deep-merge all scoped YAML files into a raw dict."""
    merged: dict = {}
    for yaml_file in sorted(config_dir.rglob("*.yaml")):
        rel = yaml_file.relative_to(config_dir)
        key_path = _resolve_key_path(rel)
        if not key_path:
            continue
        with open(yaml_file) as f:
            content = yaml.safe_load(f) or {}
        merged = _deep_merge(merged, _wrap_at_path(key_path, content))
    return merged


def _resolve_secrets(data: dict, base_path: Path) -> dict:
    from arclith.infrastructure.secret_factory import build_secret_resolver
    from arclith.infrastructure.secret_loader import resolve_dict_secrets

    resolver = build_secret_resolver(data, base_path)
    if resolver is None:
        return data
    return resolve_dict_secrets(data, resolver)


def _prepare_config(data: dict, base_path: Path) -> dict:
    """Resolve loader directives and return only AppConfig input fields."""
    resolved = _resolve_secrets(data, base_path)
    return {key: value for key, value in resolved.items() if key != "secrets"}


# ── Public loaders ────────────────────────────────────────────────────────────


def load_config_dir(path: Path) -> AppConfig:
    """Load AppConfig from a config/ directory.

    Each .yaml file is structurally mapped to an AppConfig section based on
    its relative path (Option B convention). Files are merged in lexicographic
    order. Secrets are resolved after merge using the project root as base path.
    """
    if not path.is_dir():
        raise ValueError(f"Expected a config directory, got: {path}")

    merged = _prepare_config(_build_merged_dict(path), path.parent)
    return AppConfig.model_validate(merged)


def load_config_file(path: Path) -> AppConfig:
    """Load AppConfig from a single merged YAML file.

    Intended for K8s deployments where the config/ directory has been exported
    to a single ConfigMap-mounted file via ``export_config_yaml()``.
    Secrets are resolved using the file's parent directory as base path.
    """
    if not path.is_file():
        raise ValueError(f"Expected a YAML file, got: {path}")

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    data = _prepare_config(data, path.parent)
    return AppConfig.model_validate(data)


def export_config_yaml(config_dir: Path, output_path: Path) -> None:
    """Merge a config/ directory into a single YAML file.

    The output is the canonical merged representation of all scoped config files.
    Intended for K8s ConfigMap generation — secrets mappings are preserved but
    actual secret values are never written (they are resolved at runtime).
    """
    if not config_dir.is_dir():
        raise ValueError(f"Expected a config directory, got: {config_dir}")

    merged = _build_merged_dict(config_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("# generated by arclith-cli export-config — do not edit manually\n")
        yaml.safe_dump(
            merged, f, default_flow_style=False, allow_unicode=True, sort_keys=False
        )
