from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, field_validator, model_validator

_DUCKDB_SUPPORTED_EXTENSIONS = {".csv", ".parquet", ".json", ".arrow"}


class MongoDBSettings(BaseModel):
    uri: str | None = None
    db_name: str
    collection_name: str | None = None
    multitenant: bool = False


class DuckDBSettings(BaseModel):
    path: str
    multitenant: bool = False

    @field_validator("path")
    @classmethod
    def must_be_supported_format(cls, v: str) -> str:
        p = Path(v)
        if p.is_dir() or v.endswith("/"):
            return v
        ext = p.suffix.lower()
        if ext not in _DUCKDB_SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Format '{ext}' non supporté par DuckDB. "
                f"Formats acceptés : {', '.join(sorted(_DUCKDB_SUPPORTED_EXTENSIONS))}"
            )
        return v


class MariaDBSettings(BaseModel):
    url: str | None = None
    host: str = "127.0.0.1"
    port: int = 3306
    database: str | None = None
    user: str = "app"
    password: str | None = None
    driver: str = "asyncmy"
    table_prefix: str = ""
    multitenant: bool = False

    @field_validator("port")
    @classmethod
    def must_be_valid_port(cls, v: int) -> int:
        if v <= 0 or v > 65535:
            raise ValueError("port doit etre compris entre 1 et 65535")
        return v

    @model_validator(mode="after")
    def validate_connection_target(self) -> "MariaDBSettings":
        if self.multitenant:
            return self
        if not self.url and not self.database:
            raise ValueError("database est requis quand url n'est pas configure")
        return self


class LMSettings(BaseModel):
    provider: Literal["anthropic", "openai"] = "anthropic"
    model_name: str = "claude-sonnet-4-5"
    api_key: str = ""
    base_url: str | None = None  # requis si provider="openai" (LLM local/custom)


class SoftDeleteSettings(BaseModel):
    retention_days: float | None = None

    @field_validator("retention_days")
    @classmethod
    def must_be_positive(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("retention_days doit être >= 0")
        return v


class AdaptersSettings(BaseModel):
    logger: Literal["console"] = "console"
    repository: str = "memory"
    mongodb: MongoDBSettings | None = None
    duckdb: DuckDBSettings | None = None
    mariadb: MariaDBSettings | None = None
    lm: LMSettings | None = None

    @property
    def multitenant(self) -> bool:
        match self.repository:
            case "mongodb":
                return self.mongodb.multitenant if self.mongodb else False
            case "duckdb":
                return self.duckdb.multitenant if self.duckdb else False
            case "mariadb":
                return self.mariadb.multitenant if self.mariadb else False
            case _:
                return False

    @model_validator(mode="after")
    def validate_repository_config(self) -> "AdaptersSettings":
        if self.repository == "mongodb":
            if self.mongodb is None:
                raise ValueError("repository=mongodb mais aucune section [adapters.mongodb] dans config.yaml")
        elif self.repository == "duckdb" and self.duckdb is None:
            raise ValueError("repository=duckdb mais aucune section [adapters.duckdb] dans config.yaml")
        elif self.repository == "mariadb" and self.mariadb is None:
            raise ValueError("repository=mariadb mais aucune section [adapters.mariadb] dans config.yaml")
        return self


class ApiSettings(BaseModel):
    host: str = "0.0.0.0"  # nosec B104
    port: int = 8000
    reload: bool = True


class McpSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8001


class ProbeSettings(BaseModel):
    host: str = "0.0.0.0"  # nosec B104
    port: int = 9000
    enabled: bool = True


class KeycloakSettings(BaseModel):
    url: str
    realm: str
    audience: str | None = None
    client_id: str | None = None  # Client OAuth2 pour Swagger UI (doit être public/PKCE)


class TenantSettings(BaseModel):
    vault_addr: str = "http://127.0.0.1:8200"
    vault_mount: str = "kv"
    vault_path_prefix: str
    tenant_claim: str = "sub"


class LicenseSettings(BaseModel):
    role: str = "rekipe:licensed"


class CacheSettings(BaseModel):
    backend: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://127.0.0.1:6379"
    jwks_ttl: int = 3600
    tenant_uri_ttl: int = 300


class IdempotencySettings(BaseModel):
    enabled: bool = True
    ttl_seconds: int = 86400  # 24 hours
    required: bool = False  # If True, reject POST without Idempotency-Key


class ETagSettings(BaseModel):
    enabled: bool = True


class CacheControlSettings(BaseModel):
    get_single_max_age: int = 300  # 5 minutes
    get_list_max_age: int = 60  # 1 minute


class HttpSettings(BaseModel):
    idempotency: IdempotencySettings = IdempotencySettings()
    etag: ETagSettings = ETagSettings()
    cache_control: CacheControlSettings = CacheControlSettings()


class AppSettings(BaseModel):
    name: str = "arclith-service"
    version: str = "0.0.0"
    description: str = "API service built with arclith framework"


class AppConfig(BaseModel):
    app: AppSettings = AppSettings()
    adapters: AdaptersSettings = AdaptersSettings()
    soft_delete: SoftDeleteSettings = SoftDeleteSettings()
    api: ApiSettings = ApiSettings()
    mcp: McpSettings = McpSettings()
    probe: ProbeSettings = ProbeSettings()
    http: HttpSettings = HttpSettings()
    keycloak: KeycloakSettings | None = None
    tenant: TenantSettings | None = None
    license: LicenseSettings | None = None
    cache: CacheSettings = CacheSettings()


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
    from contextlib import suppress

    from arclith.infrastructure.secret_factory import build_secret_resolver
    from arclith.infrastructure.secret_loader import resolve_dict_secrets

    resolver = build_secret_resolver(data, base_path)
    if resolver:
        with suppress(Exception):
            data = resolve_dict_secrets(data, resolver)
    return data


# ── Public loaders ────────────────────────────────────────────────────────────

def load_config_dir(path: Path) -> AppConfig:
    """Load AppConfig from a config/ directory.

    Each .yaml file is structurally mapped to an AppConfig section based on
    its relative path (Option B convention). Files are merged in lexicographic
    order. Secrets are resolved after merge using the project root as base path.
    """
    if not path.is_dir():
        raise ValueError(f"Expected a config directory, got: {path}")

    merged = _resolve_secrets(_build_merged_dict(path), path.parent)
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

    data = _resolve_secrets(data, path.parent)
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
        yaml.safe_dump(merged, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
