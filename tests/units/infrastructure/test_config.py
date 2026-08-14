import tempfile
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from arclith.infrastructure.config import (
    AppConfig,
    CacheControlSettings,
    CommandBusSettings,
    DuckDBSettings,
    LangGraphSettings,
    LangSmithSettings,
    MariaDBSettings,
    OpenTelemetrySettings,
    RabbitMQCommandBusSettings,
    SoftDeleteSettings,
    StorageSettings,
    _deep_merge,
    _resolve_key_path,
    export_config_yaml,
    load_config_dir,
    load_config_file,
)


# ── AppConfig defaults ────────────────────────────────────────────────────────

def test_default_config_uses_memory():
    assert AppConfig().adapters.repository == "memory"
    assert AppConfig().adapters.storage is None
    assert AppConfig().adapters.observability.enabled == []
    assert AppConfig().command_bus.enabled == []


def test_custom_repository_adapter_name_is_allowed():
    config = AppConfig.model_validate({"adapters": {"repository": "customdb"}})

    assert config.adapters.repository == "customdb"
    assert config.adapters.multitenant is False


def test_unknown_logger_adapter_is_rejected():
    with pytest.raises(ValidationError, match="logger=custom non supporte"):
        AppConfig.model_validate({"adapters": {"logger": "custom"}})


def test_default_retention_is_none():
    assert AppConfig().soft_delete.retention_days is None


# ── _resolve_key_path ─────────────────────────────────────────────────────────

def test_resolve_root_file():
    assert _resolve_key_path(Path("app.yaml")) == ["app"]


def test_resolve_root_soft_delete():
    assert _resolve_key_path(Path("soft_delete.yaml")) == ["soft_delete"]


def test_resolve_root_secrets():
    assert _resolve_key_path(Path("secrets.yaml")) == ["secrets"]


def test_resolve_adapters_selector():
    assert _resolve_key_path(Path("adapters/adapters.yaml")) == ["adapters"]


def test_resolve_output_adapter():
    assert _resolve_key_path(Path("adapters/outbound/mongodb.yaml")) == ["adapters", "mongodb"]
    assert _resolve_key_path(Path("adapters/outbound/duckdb.yaml")) == ["adapters", "duckdb"]
    assert _resolve_key_path(Path("adapters/outbound/mariadb.yaml")) == ["adapters", "mariadb"]
    assert _resolve_key_path(Path("adapters/outbound/storage.yaml")) == ["adapters", "storage"]


def test_resolve_input_alias_fastapi():
    assert _resolve_key_path(Path("adapters/inbound/fastapi.yaml")) == ["api"]


def test_resolve_input_alias_fastmcp():
    assert _resolve_key_path(Path("adapters/inbound/fastmcp.yaml")) == ["mcp"]


def test_resolve_input_langgraph():
    assert _resolve_key_path(Path("adapters/inbound/langgraph.yaml")) == ["langgraph"]


def test_resolve_input_no_alias():
    assert _resolve_key_path(Path("adapters/inbound/keycloak.yaml")) == ["keycloak"]
    assert _resolve_key_path(Path("adapters/inbound/cache.yaml")) == ["cache"]
    assert _resolve_key_path(Path("adapters/inbound/tenant.yaml")) == ["tenant"]


def test_resolve_unknown_path_returns_empty():
    assert _resolve_key_path(Path("some/deep/unknown/path.yaml")) == []


# ── _deep_merge ───────────────────────────────────────────────────────────────

def test_deep_merge_simple():
    result = _deep_merge({"a": 1}, {"b": 2})
    assert result == {"a": 1, "b": 2}


def test_deep_merge_override():
    result = _deep_merge({"a": 1, "b": 2}, {"b": 99})
    assert result == {"a": 1, "b": 99}


def test_deep_merge_nested():
    base = {"adapters": {"repository": "memory", "mongodb": {"db_name": "old"}}}
    override = {"adapters": {"mongodb": {"db_name": "new", "multitenant": True}}}
    result = _deep_merge(base, override)
    assert result["adapters"]["repository"] == "memory"
    assert result["adapters"]["mongodb"]["db_name"] == "new"
    assert result["adapters"]["mongodb"]["multitenant"] is True


def test_deep_merge_does_not_mutate_base():
    base = {"a": {"b": 1}}
    _deep_merge(base, {"a": {"b": 2}})
    assert base["a"]["b"] == 1


# ── load_config_dir ───────────────────────────────────────────────────────────

def _make_config_dir(files: dict[str, dict]) -> Path:
    """Helper: create a temp config/ directory with the given files."""
    tmp = Path(tempfile.mkdtemp())
    for rel, content in files.items():
        dest = tmp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(yaml.dump(content))
    return tmp


def test_load_config_dir_empty_uses_defaults():
    tmp = Path(tempfile.mkdtemp())
    config = load_config_dir(tmp)
    assert config.adapters.repository == "memory"


def test_load_config_dir_memory():
    path = _make_config_dir({"adapters/adapters.yaml": {"repository": "memory"}})
    config = load_config_dir(path)
    assert config.adapters.repository == "memory"


def test_load_config_dir_app_section():
    path = _make_config_dir({"app.yaml": {"name": "TestApp", "version": "1.2.3"}})
    config = load_config_dir(path)
    assert config.app.name == "TestApp"
    assert config.app.version == "1.2.3"


def test_load_config_dir_api_via_fastapi_alias():
    path = _make_config_dir({"adapters/inbound/fastapi.yaml": {"port": 9999}})
    config = load_config_dir(path)
    assert config.api.port == 9999


def test_load_config_dir_mcp_via_fastmcp_alias():
    path = _make_config_dir({"adapters/inbound/fastmcp.yaml": {"port": 8888}})
    config = load_config_dir(path)
    assert config.mcp.port == 8888


def test_load_config_dir_probe_scoped():
    path = _make_config_dir({
        "adapters/inbound/probe.yaml": {
            "host": "127.0.0.1",
            "port": 9100,
            "enabled": False,
        }
    })
    config = load_config_dir(path)
    assert config.probe.host == "127.0.0.1"
    assert config.probe.port == 9100
    assert config.probe.enabled is False


def test_load_config_dir_cache_scoped():
    path = _make_config_dir({
        "adapters/inbound/cache.yaml": {
            "backend": "memory",
            "jwks_ttl": 1200,
            "tenant_uri_ttl": 180,
        }
    })
    config = load_config_dir(path)
    assert config.cache.backend == "memory"
    assert config.cache.jwks_ttl == 1200
    assert config.cache.tenant_uri_ttl == 180


def test_load_config_dir_redis_cache_scoped():
    path = _make_config_dir({
        "adapters/inbound/cache.yaml": {
            "backend": "redis",
            "redis_url": "redis://cache:6379/0",
            "jwks_ttl": 900,
            "tenant_uri_ttl": 120,
        }
    })
    config = load_config_dir(path)
    assert config.cache.backend == "redis"
    assert config.cache.redis_url == "redis://cache:6379/0"
    assert config.cache.jwks_ttl == 900
    assert config.cache.tenant_uri_ttl == 120


def test_load_config_dir_mongodb_scoped():
    path = _make_config_dir({
        "adapters/adapters.yaml": {"repository": "mongodb"},
        "adapters/outbound/mongodb.yaml": {"db_name": "mydb", "multitenant": False},
    })
    config = load_config_dir(path)
    assert config.adapters.repository == "mongodb"
    assert config.adapters.mongodb is not None
    assert config.adapters.mongodb.db_name == "mydb"


def test_load_config_dir_duckdb_scoped():
    path = _make_config_dir({
        "adapters/adapters.yaml": {"repository": "duckdb"},
        "adapters/outbound/duckdb.yaml": {"path": "data/"},
    })
    config = load_config_dir(path)
    assert config.adapters.duckdb is not None
    assert config.adapters.duckdb.path == "data/"


def test_load_config_dir_mariadb_scoped():
    path = _make_config_dir({
        "adapters/adapters.yaml": {"repository": "mariadb"},
        "adapters/outbound/mariadb.yaml": {"database": "demo", "user": "app"},
    })
    config = load_config_dir(path)
    assert config.adapters.mariadb is not None
    assert config.adapters.mariadb.database == "demo"
    assert config.adapters.mariadb.user == "app"


def test_load_config_dir_storage_filesystem_scoped():
    path = _make_config_dir({
        "adapters/outbound/storage.yaml": {
            "adapter": "filesystem",
            "root_path": "/data/files",
            "prefix": "uploads",
            "create_root": False,
            "multitenant": False,
        },
    })
    config = load_config_dir(path)

    assert config.adapters.storage is not None
    assert config.adapters.storage.adapter == "filesystem"
    assert config.adapters.storage.root_path == "/data/files"
    assert config.adapters.storage.prefix == "uploads"
    assert config.adapters.storage.create_root is False
    assert config.adapters.storage.multitenant is False


def test_load_config_dir_storage_s3_scoped():
    path = _make_config_dir({
        "adapters/outbound/storage.yaml": {
            "adapter": "s3",
            "bucket_name": "arclith-files",
            "prefix": "uploads",
            "region_name": "eu-west-3",
            "endpoint_url": "http://127.0.0.1:9000",
            "force_path_style": True,
            "multitenant": False,
        },
    })
    config = load_config_dir(path)

    assert config.adapters.storage is not None
    assert config.adapters.storage.adapter == "s3"
    assert config.adapters.storage.bucket_name == "arclith-files"
    assert config.adapters.storage.prefix == "uploads"
    assert config.adapters.storage.region_name == "eu-west-3"
    assert config.adapters.storage.endpoint_url == "http://127.0.0.1:9000"
    assert config.adapters.storage.force_path_style is True
    assert config.adapters.storage.multitenant is False


def test_load_config_dir_storage_gcs_scoped():
    path = _make_config_dir({
        "adapters/outbound/storage.yaml": {
            "adapter": "gcs",
            "bucket_name": "arclith-files",
            "prefix": "uploads",
            "project_id": "project-a",
            "credentials_json_b64": "encoded",
            "multitenant": False,
        },
    })
    config = load_config_dir(path)

    assert config.adapters.storage is not None
    assert config.adapters.storage.adapter == "gcs"
    assert config.adapters.storage.bucket_name == "arclith-files"
    assert config.adapters.storage.prefix == "uploads"
    assert config.adapters.storage.project_id == "project-a"
    assert config.adapters.storage.credentials_json_b64 == "encoded"
    assert config.adapters.storage.multitenant is False


def test_load_config_dir_storage_azure_blob_scoped():
    path = _make_config_dir({
        "adapters/outbound/storage.yaml": {
            "adapter": "azure-blob",
            "account_url": "https://account.blob.core.windows.net",
            "container_name": "arclith-files",
            "prefix": "uploads",
            "connection_string": "UseDevelopmentStorage=true",
            "account_key": None,
            "sas_token": None,
            "use_default_credential": False,
            "multitenant": False,
        },
    })
    config = load_config_dir(path)

    assert config.adapters.storage is not None
    assert config.adapters.storage.adapter == "azure-blob"
    assert config.adapters.storage.account_url == "https://account.blob.core.windows.net"
    assert config.adapters.storage.container_name == "arclith-files"
    assert config.adapters.storage.prefix == "uploads"
    assert config.adapters.storage.connection_string == "UseDevelopmentStorage=true"
    assert config.adapters.storage.account_key is None
    assert config.adapters.storage.sas_token is None
    assert config.adapters.storage.use_default_credential is False
    assert config.adapters.storage.multitenant is False


def test_load_config_dir_storage_azure_blob_credentials_from_secret_mapping(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    path = _make_config_dir({
        "adapters/outbound/storage.yaml": {
            "adapter": "azure-blob",
            "account_url": "https://account.blob.core.windows.net",
            "container_name": "arclith-files",
            "connection_string": None,
            "multitenant": False,
        },
        "secrets.yaml": {
            "resolver": "env",
            "mappings": {
                "adapters.storage.connection_string": "AZURE_STORAGE_CONNECTION_STRING",
            },
        },
    })
    config = load_config_dir(path)

    assert config.adapters.storage is not None
    assert config.adapters.storage.adapter == "azure-blob"
    assert config.adapters.storage.connection_string == "UseDevelopmentStorage=true"


def test_load_config_dir_storage_gcs_credentials_from_secret_mapping(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GCS_SERVICE_ACCOUNT_JSON_B64", "encoded-from-env")
    path = _make_config_dir({
        "adapters/outbound/storage.yaml": {
            "adapter": "gcs",
            "bucket_name": "arclith-files",
            "credentials_json_b64": None,
        },
        "secrets.yaml": {
            "resolver": "env",
            "mappings": {
                "adapters.storage.credentials_json_b64": "GCS_SERVICE_ACCOUNT_JSON_B64",
            },
        },
    })
    config = load_config_dir(path)

    assert config.adapters.storage is not None
    assert config.adapters.storage.adapter == "gcs"
    assert config.adapters.storage.credentials_json_b64 == "encoded-from-env"


@pytest.mark.parametrize(
    ("payload", "missing"),
    [
        ({"adapter": "filesystem"}, "root_path"),
        ({"adapter": "s3"}, "bucket_name"),
        ({"adapter": "gcs"}, "bucket_name"),
        ({"adapter": "azure-blob", "account_url": "https://account.blob.core.windows.net"}, "container_name"),
    ],
)
def test_storage_single_tenant_requires_backend_target(payload: dict[str, str], missing: str) -> None:
    with pytest.raises(ValidationError, match=missing):
        StorageSettings.model_validate(payload)


@pytest.mark.parametrize("adapter", ["filesystem", "s3", "azure-blob", "gcs"])
def test_storage_multitenant_allows_tenant_resolved_target(adapter: str) -> None:
    settings = StorageSettings.model_validate({"adapter": adapter, "multitenant": True})

    assert settings.adapter == adapter
    assert settings.multitenant is True


@pytest.mark.parametrize("prefix", ["../uploads", "uploads/../private", "/uploads", "uploads//drafts"])
def test_storage_prefix_rejects_traversal(prefix: str) -> None:
    with pytest.raises(ValidationError, match="storage key"):
        StorageSettings.model_validate({
            "adapter": "filesystem",
            "root_path": "/data/files",
            "prefix": prefix,
        })


def test_load_config_dir_langsmith_scoped():
    path = _make_config_dir({
        "adapters/adapters.yaml": {"observability": {"enabled": ["langsmith"]}},
        "adapters/outbound/langsmith.yaml": {
            "tracing": True,
            "project": "agent-tests",
            "endpoint": "https://eu.api.smith.langchain.com",
            "api_key_env": "LANGSMITH_API_KEY",
            "studio": "langgraph",
            "langgraph_api_min_version": "0.11.0",
        },
    })
    config = load_config_dir(path)
    assert config.adapters.observability.enabled == ["langsmith"]
    assert config.adapters.observability.is_enabled("langsmith") is True
    assert config.adapters.langsmith is not None
    assert config.adapters.langsmith.project == "agent-tests"
    assert config.adapters.langsmith.endpoint == "https://eu.api.smith.langchain.com"


def test_load_config_dir_opentelemetry_scoped():
    path = _make_config_dir({
        "adapters/adapters.yaml": {"observability": {"enabled": ["opentelemetry"]}},
        "adapters/outbound/opentelemetry.yaml": {
            "service_name": "demo-api",
            "endpoint": "http://otel-collector:4318",
            "traces_endpoint": "http://otel-collector:4318/v1/custom-traces",
            "metrics_endpoint": "http://otel-collector:4318/v1/custom-metrics",
            "protocol": "http/protobuf",
            "traces": True,
            "metrics": True,
            "instrument_fastapi": True,
            "metrics_export_interval_millis": 15000,
        },
    })
    config = load_config_dir(path)
    assert config.adapters.observability.enabled == ["opentelemetry"]
    assert config.adapters.observability.is_enabled("opentelemetry") is True
    assert config.adapters.opentelemetry is not None
    assert config.adapters.opentelemetry.service_name == "demo-api"
    assert config.adapters.opentelemetry.endpoint == "http://otel-collector:4318"
    assert config.adapters.opentelemetry.traces_endpoint == "http://otel-collector:4318/v1/custom-traces"
    assert config.adapters.opentelemetry.metrics_endpoint == "http://otel-collector:4318/v1/custom-metrics"
    assert config.adapters.opentelemetry.metrics is True
    assert config.adapters.opentelemetry.metrics_export_interval_millis == 15000


def test_load_config_dir_parallel_observability_scoped():
    path = _make_config_dir({
        "adapters/adapters.yaml": {"observability": {"enabled": ["langsmith", "opentelemetry"]}},
        "adapters/outbound/langsmith.yaml": {"project": "agent-tests"},
        "adapters/outbound/opentelemetry.yaml": {"instrument_fastapi": True},
    })
    config = load_config_dir(path)

    assert config.adapters.observability.enabled == ["langsmith", "opentelemetry"]
    assert config.adapters.langsmith is not None
    assert config.adapters.opentelemetry is not None


def test_load_config_dir_langgraph_scoped():
    path = _make_config_dir({
        "adapters/inbound/langgraph.yaml": {
            "name": "todo_agent",
            "graph": "todo_agent",
            "entrypoint": "./src/demo_service/adapters/inbound/langgraph/agent.py:agent",
            "env": ".env",
        },
    })
    config = load_config_dir(path)
    assert config.langgraph is not None
    assert config.langgraph.name == "todo_agent"
    assert config.langgraph.graph == "todo_agent"
    assert config.langgraph.entrypoint == "./src/demo_service/adapters/inbound/langgraph/agent.py:agent"
    assert config.langgraph.env == ".env"


def test_langsmith_observability_requires_scoped_config():
    with pytest.raises(ValidationError, match="observability.enabled contient langsmith"):
        AppConfig.model_validate({"adapters": {"observability": {"enabled": ["langsmith"]}}})


def test_opentelemetry_observability_requires_scoped_config():
    with pytest.raises(ValidationError, match="observability.enabled contient opentelemetry"):
        AppConfig.model_validate({"adapters": {"observability": {"enabled": ["opentelemetry"]}}})


def test_observability_scalar_format_is_rejected():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"adapters": {"observability": "langsmith"}})


def test_observability_enabled_rejects_duplicates():
    with pytest.raises(ValidationError, match="doublons"):
        AppConfig.model_validate({
            "adapters": {
                "observability": {"enabled": ["langsmith", "langsmith"]},
                "langsmith": {"project": "agent-tests"},
            }
        })


def test_langgraph_settings_defaults():
    settings = LangGraphSettings(entrypoint="./src/demo_service/adapters/inbound/langgraph/agent.py:agent")

    assert settings.name == "agent"
    assert settings.graph == "agent"
    assert settings.env == ".env"


def test_langsmith_settings_defaults():
    settings = LangSmithSettings(project="agent-tests")

    assert settings.tracing is True
    assert settings.endpoint == "https://api.smith.langchain.com"
    assert settings.api_key_env == "LANGSMITH_API_KEY"
    assert settings.studio == "langgraph"
    assert settings.langgraph_api_min_version == "0.11.0"


def test_opentelemetry_settings_defaults():
    settings = OpenTelemetrySettings()

    assert settings.service_name is None
    assert settings.endpoint == "http://localhost:4318"
    assert settings.traces_endpoint is None
    assert settings.metrics_endpoint is None
    assert settings.protocol == "http/protobuf"
    assert settings.headers_env == "OTEL_EXPORTER_OTLP_HEADERS"
    assert settings.traces is True
    assert settings.metrics is False
    assert settings.instrument_fastapi is True
    assert settings.metrics_export_interval_millis == 60000


def test_opentelemetry_settings_rejects_legacy_enabled_flag():
    with pytest.raises(ValidationError):
        OpenTelemetrySettings.model_validate({"enabled": True})


def test_opentelemetry_settings_validates_interval():
    with pytest.raises(ValidationError):
        OpenTelemetrySettings(metrics_export_interval_millis=0)


def test_load_config_dir_soft_delete():
    path = _make_config_dir({"soft_delete.yaml": {"retention_days": 7}})
    config = load_config_dir(path)
    assert config.soft_delete.retention_days == 7


def test_load_config_dir_unknown_path_ignored():
    path = _make_config_dir({
        "some/deep/unknown.yaml": {"foo": "bar"},
        "app.yaml": {"name": "OK"},
    })
    config = load_config_dir(path)
    assert config.app.name == "OK"


def test_load_config_dir_raises_if_not_directory():
    with tempfile.NamedTemporaryFile(suffix=".yaml") as f:
        with pytest.raises(ValueError, match="config directory"):
            load_config_dir(Path(f.name))


# ── DuckDBSettings / SoftDeleteSettings ──────────────────────────────────────

@pytest.mark.parametrize(
    "path",
    [
        "data/entities.csv",
        "data/entities.parquet",
        "data/entities.json",
        "data/entities.arrow",
    ],
)
def test_duckdb_settings_file_path_supported_extensions(path: str):
    s = DuckDBSettings(path=path)
    assert s.path == path


def test_duckdb_settings_directory_path():
    s = DuckDBSettings(path="data/")
    assert s.path == "data/"


def test_duckdb_settings_invalid_extension():
    with pytest.raises(ValidationError, match=r"Format '\.txt' non supporté par DuckDB"):
        DuckDBSettings(path="data/file.txt")


def test_soft_delete_negative_raises():
    with pytest.raises(ValidationError):
        SoftDeleteSettings(retention_days=-1)


def test_soft_delete_zero_is_valid():
    s = SoftDeleteSettings(retention_days=0)
    assert s.retention_days == 0


def test_cache_control_rejects_negative_max_age():
    with pytest.raises(ValidationError, match="cache_control max-age doit etre >= 0"):
        CacheControlSettings(get_single_max_age=-1)


def test_cache_control_zero_max_age_is_valid():
    settings = CacheControlSettings(get_single_max_age=0, get_list_max_age=0)

    assert settings.get_single_max_age == 0
    assert settings.get_list_max_age == 0


def test_command_bus_settings_detect_enabled_adapter():
    settings = CommandBusSettings(enabled=["rabbitmq"])

    assert settings.is_enabled("rabbitmq") is True


def test_command_bus_settings_rejects_duplicate_enabled_adapter():
    with pytest.raises(ValidationError, match="command_bus.enabled ne doit pas contenir de doublons"):
        CommandBusSettings(enabled=["rabbitmq", "rabbitmq"])


def test_rabbitmq_command_bus_settings_rejects_unbounded_prefetch():
    with pytest.raises(ValidationError, match="prefetch/concurrency doivent etre > 0"):
        RabbitMQCommandBusSettings(prefetch=0)


def test_rabbitmq_command_bus_settings_rejects_empty_names():
    with pytest.raises(ValidationError, match="ne doivent pas etre vides"):
        RabbitMQCommandBusSettings(queue=" ")


def test_mongodb_uri_optional_at_parse_time():
    config = AppConfig.model_validate({
        "adapters": {
            "repository": "mongodb",
            "mongodb": {"db_name": "test"},
        }
    })
    assert config.adapters.mongodb is not None
    assert config.adapters.mongodb.uri is None


def test_mongodb_multitenant_no_uri_required():
    config = AppConfig.model_validate({
        "adapters": {
            "repository": "mongodb",
            "mongodb": {"db_name": "test", "multitenant": True},
        }
    })
    assert config.adapters.multitenant is True


def test_mariadb_settings_with_database():
    settings = MariaDBSettings(database="demo", port=3307, table_prefix="app_")

    assert settings.database == "demo"
    assert settings.port == 3307
    assert settings.table_prefix == "app_"


def test_mariadb_settings_with_url_only():
    settings = MariaDBSettings(url="mysql+asyncmy://app@localhost:3306/demo")

    assert settings.url == "mysql+asyncmy://app@localhost:3306/demo"
    assert settings.database is None


def test_mariadb_settings_requires_url_or_database():
    with pytest.raises(ValidationError, match="database est requis quand url n'est pas configure"):
        MariaDBSettings()


def test_mariadb_multitenant_no_database_required():
    config = AppConfig.model_validate({
        "adapters": {
            "repository": "mariadb",
            "mariadb": {"multitenant": True},
        }
    })

    assert config.adapters.mariadb is not None
    assert config.adapters.multitenant is True


def test_duckdb_requires_section():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"adapters": {"repository": "duckdb"}})


def test_mongodb_requires_section():
    with pytest.raises(ValidationError, match=r"repository=mongodb mais aucune section \[adapters.mongodb\]"):
        AppConfig.model_validate({"adapters": {"repository": "mongodb"}})


def test_mariadb_requires_section():
    with pytest.raises(ValidationError, match=r"repository=mariadb mais aucune section \[adapters.mariadb\]"):
        AppConfig.model_validate({"adapters": {"repository": "mariadb"}})


# ── load_config_file ──────────────────────────────────────────────────────────

def test_load_config_file_simple():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump({"adapters": {"repository": "memory"}}, f)
        path = Path(f.name)
    config = load_config_file(path)
    path.unlink()
    assert config.adapters.repository == "memory"


def test_load_config_file_full_sections():
    data = {
        "app": {"name": "MyApp"},
        "api": {"port": 9001},
        "adapters": {"repository": "memory"},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        path = Path(f.name)
    config = load_config_file(path)
    path.unlink()
    assert config.app.name == "MyApp"
    assert config.api.port == 9001


def test_load_config_file_raises_if_not_file():
    with pytest.raises(ValueError, match="YAML file"):
        load_config_file(Path(tempfile.mkdtemp()))


# ── export_config_yaml ────────────────────────────────────────────────────────

def test_export_config_yaml_creates_file():
    config_dir = _make_config_dir({
        "app.yaml": {"name": "ExportTest"},
        "adapters/adapters.yaml": {"repository": "memory"},
    })
    out = config_dir / "config.yaml"
    export_config_yaml(config_dir, out)
    assert out.exists()


def test_export_config_yaml_content_is_valid_yaml():
    config_dir = _make_config_dir({
        "app.yaml": {"name": "RoundTrip"},
        "adapters/adapters.yaml": {"repository": "memory"},
        "adapters/inbound/fastapi.yaml": {"port": 7777},
    })
    out = config_dir / "config.yaml"
    export_config_yaml(config_dir, out)
    with open(out) as f:
        data = yaml.safe_load(f)
    assert data["app"]["name"] == "RoundTrip"
    assert data["api"]["port"] == 7777


def test_export_config_yaml_round_trip():
    """load_config_dir and load_config_file must produce identical AppConfig."""
    config_dir = _make_config_dir({
        "app.yaml": {"name": "RoundTrip", "version": "1.0.0"},
        "soft_delete.yaml": {"retention_days": 14},
        "adapters/adapters.yaml": {"repository": "duckdb"},
        "adapters/outbound/duckdb.yaml": {"path": "data/"},
        "adapters/outbound/storage.yaml": {
            "adapter": "filesystem",
            "root_path": "/data/files",
            "prefix": "uploads",
            "create_root": True,
        },
        "adapters/inbound/fastapi.yaml": {"port": 8765},
    })
    out = config_dir / "config.yaml"
    export_config_yaml(config_dir, out)

    from_dir = load_config_dir(config_dir)
    from_file = load_config_file(out)

    assert from_dir.app.name == from_file.app.name
    assert from_dir.soft_delete.retention_days == from_file.soft_delete.retention_days
    assert from_dir.adapters.repository == from_file.adapters.repository
    assert from_dir.adapters.storage == from_file.adapters.storage
    assert from_dir.api.port == from_file.api.port


def test_export_config_yaml_raises_if_not_directory():
    with tempfile.NamedTemporaryFile(suffix=".yaml") as f:
        with pytest.raises(ValueError, match="config directory"):
            export_config_yaml(Path(f.name), Path("/tmp/out.yaml"))


def test_export_config_yaml_has_generated_header():
    config_dir = _make_config_dir({"app.yaml": {"name": "Header"}})
    out = config_dir / "config.yaml"
    export_config_yaml(config_dir, out)
    content = out.read_text()
    assert "generated" in content
    assert "do not edit" in content


# ── LMSettings ────────────────────────────────────────────────────────────────

def test_adapters_lm_defaults_to_none():
    assert AppConfig().adapters.lm is None


def test_adapters_lm_parsed_from_yaml():
    config = AppConfig.model_validate({
        "adapters": {
            "lm": {
                "provider": "anthropic",
                "model_name": "claude-opus-4-5",
                "api_key": "sk-ant-test",
            }
        }
    })
    assert config.adapters.lm is not None
    assert config.adapters.lm.provider == "anthropic"
    assert config.adapters.lm.model_name == "claude-opus-4-5"
    assert config.adapters.lm.api_key == "sk-ant-test"
    assert config.adapters.lm.base_url is None


def test_adapters_lm_openai_with_base_url():
    config = AppConfig.model_validate({
        "adapters": {
            "lm": {
                "provider": "openai",
                "model_name": "llama3",
                "api_key": "ollama",
                "base_url": "http://localhost:11434/v1",
            }
        }
    })
    assert config.adapters.lm is not None
    assert config.adapters.lm.provider == "openai"
    assert config.adapters.lm.base_url == "http://localhost:11434/v1"


def test_adapters_lm_loaded_from_config_dir():
    config_dir = _make_config_dir({
        "adapters/adapters.yaml": {"repository": "memory"},
        "adapters/outbound/lm.yaml": {"provider": "anthropic", "model_name": "claude-sonnet-4-5", "api_key": ""},
    })
    config = load_config_dir(config_dir)
    assert config.adapters.lm is not None
    assert config.adapters.lm.provider == "anthropic"


def test_adapters_lm_api_key_loaded_from_env_mapping(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    config_dir = _make_config_dir({
        "adapters/adapters.yaml": {"repository": "memory"},
        "adapters/outbound/lm.yaml": {
            "provider": "openai",
            "model_name": "gpt-4o-mini",
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
        },
        "secrets.yaml": {
            "resolver": "env",
            "mappings": {
                "adapters.lm.api_key": "OPENAI_API_KEY",
            },
        },
    })

    config = load_config_dir(config_dir)

    assert config.adapters.lm is not None
    assert config.adapters.lm.api_key == "sk-openai"


def test_adapters_lm_missing_env_secret_raises_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config_dir = _make_config_dir({
        "adapters/adapters.yaml": {"repository": "memory"},
        "adapters/outbound/lm.yaml": {
            "provider": "openai",
            "model_name": "gpt-4o-mini",
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
        },
        "secrets.yaml": {
            "resolver": "env",
            "mappings": {
                "adapters.lm.api_key": "OPENAI_API_KEY",
            },
        },
    })

    with pytest.raises(RuntimeError, match="Secrets non résolus.*adapters.lm.api_key"):
        load_config_dir(config_dir)


def test_adapters_lm_anthropic_api_key_loaded_from_env_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    config_dir = _make_config_dir({
        "adapters/adapters.yaml": {"repository": "memory"},
        "adapters/outbound/lm.yaml": {
            "provider": "anthropic",
            "model_name": "claude-dev-model",
            "api_key": "",
        },
        "secrets.yaml": {
            "resolver": "env",
            "mappings": {
                "adapters.lm.api_key": "ANTHROPIC_API_KEY",
            },
        },
    })

    config = load_config_dir(config_dir)

    assert config.adapters.lm is not None
    assert config.adapters.lm.provider == "anthropic"
    assert config.adapters.lm.model_name == "claude-dev-model"
    assert config.adapters.lm.api_key == "sk-ant-env"


def test_adapters_lm_missing_anthropic_env_secret_raises_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config_dir = _make_config_dir({
        "adapters/adapters.yaml": {"repository": "memory"},
        "adapters/outbound/lm.yaml": {
            "provider": "anthropic",
            "model_name": "claude-dev-model",
            "api_key": "",
        },
        "secrets.yaml": {
            "resolver": "env",
            "mappings": {
                "adapters.lm.api_key": "ANTHROPIC_API_KEY",
            },
        },
    })

    with pytest.raises(RuntimeError, match="Secrets non résolus.*adapters.lm.api_key"):
        load_config_dir(config_dir)


def test_adapters_mongodb_uri_loaded_from_env_mapping(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://env-mongo:27017")
    config_dir = _make_config_dir({
        "adapters/adapters.yaml": {"repository": "mongodb"},
        "adapters/outbound/mongodb.yaml": {
            "uri": None,
            "db_name": "demo_shared",
            "collection_name": None,
            "multitenant": False,
        },
        "secrets.yaml": {
            "resolver": "env",
            "mappings": {
                "adapters.mongodb.uri": "MONGODB_URI",
            },
        },
    })

    config = load_config_dir(config_dir)

    assert config.adapters.mongodb is not None
    assert config.adapters.mongodb.uri == "mongodb://env-mongo:27017"
    assert config.adapters.mongodb.db_name == "demo_shared"


def test_adapters_mariadb_url_and_password_loaded_from_env_mapping(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MARIADB_URL", "mysql+asyncmy://env-app@db:3306/env_demo")
    monkeypatch.setenv("MARIADB_PASSWORD", "env-password")
    config_dir = _make_config_dir({
        "adapters/adapters.yaml": {"repository": "mariadb"},
        "adapters/outbound/mariadb.yaml": {
            "url": None,
            "host": "127.0.0.1",
            "port": 3306,
            "database": "demo_shared",
            "user": "app",
            "password": None,
            "driver": "asyncmy",
            "table_prefix": "",
            "multitenant": False,
        },
        "secrets.yaml": {
            "resolver": "env",
            "mappings": {
                "adapters.mariadb.url": "MARIADB_URL",
                "adapters.mariadb.password": "MARIADB_PASSWORD",
            },
        },
    })

    config = load_config_dir(config_dir)

    assert config.adapters.mariadb is not None
    assert config.adapters.mariadb.url == "mysql+asyncmy://env-app@db:3306/env_demo"
    assert config.adapters.mariadb.password == "env-password"


def test_cache_redis_url_loaded_from_env_mapping(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379/0")
    config_dir = _make_config_dir({
        "adapters/inbound/cache.yaml": {
            "backend": "redis",
            "redis_url": "",
            "jwks_ttl": 900,
            "tenant_uri_ttl": 120,
        },
        "secrets.yaml": {
            "resolver": "env",
            "mappings": {
                "cache.redis_url": "REDIS_URL",
            },
        },
    })

    config = load_config_dir(config_dir)

    assert config.cache.backend == "redis"
    assert config.cache.redis_url == "redis://cache:6379/0"


def test_cache_missing_redis_env_secret_raises_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    config_dir = _make_config_dir({
        "adapters/inbound/cache.yaml": {
            "backend": "redis",
            "redis_url": "",
        },
        "secrets.yaml": {
            "resolver": "env",
            "mappings": {
                "cache.redis_url": "REDIS_URL",
            },
        },
    })

    with pytest.raises(RuntimeError, match="Secrets non résolus.*cache.redis_url"):
        load_config_dir(config_dir)
