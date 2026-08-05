import tempfile
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from arclith.infrastructure.config import (
    AppConfig,
    DuckDBSettings,
    LangGraphSettings,
    LangSmithSettings,
    MariaDBSettings,
    SoftDeleteSettings,
    _deep_merge,
    _resolve_key_path,
    export_config_yaml,
    load_config_dir,
    load_config_file,
)


# ── AppConfig defaults ────────────────────────────────────────────────────────

def test_default_config_uses_memory():
    assert AppConfig().adapters.repository == "memory"
    assert AppConfig().adapters.observability == "none"


def test_custom_repository_adapter_name_is_allowed():
    config = AppConfig.model_validate({"adapters": {"repository": "customdb"}})

    assert config.adapters.repository == "customdb"
    assert config.adapters.multitenant is False


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


def test_load_config_dir_langsmith_scoped():
    path = _make_config_dir({
        "adapters/adapters.yaml": {"observability": "langsmith"},
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
    assert config.adapters.observability == "langsmith"
    assert config.adapters.langsmith is not None
    assert config.adapters.langsmith.project == "agent-tests"
    assert config.adapters.langsmith.endpoint == "https://eu.api.smith.langchain.com"


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
    with pytest.raises(ValidationError, match="observability=langsmith"):
        AppConfig.model_validate({"adapters": {"observability": "langsmith"}})


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

def test_duckdb_settings_file_path():
    s = DuckDBSettings(path="data/entities.csv")
    assert s.path == "data/entities.csv"


def test_duckdb_settings_directory_path():
    s = DuckDBSettings(path="data/")
    assert s.path == "data/"


def test_duckdb_settings_invalid_extension():
    with pytest.raises(ValidationError):
        DuckDBSettings(path="data/file.txt")


def test_soft_delete_negative_raises():
    with pytest.raises(ValidationError):
        SoftDeleteSettings(retention_days=-1)


def test_soft_delete_zero_is_valid():
    s = SoftDeleteSettings(retention_days=0)
    assert s.retention_days == 0


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


def test_mariadb_settings_requires_url_or_database():
    with pytest.raises(ValidationError):
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
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"adapters": {"repository": "mongodb"}})


def test_mariadb_requires_section():
    with pytest.raises(ValidationError):
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
        "adapters/inbound/fastapi.yaml": {"port": 8765},
    })
    out = config_dir / "config.yaml"
    export_config_yaml(config_dir, out)

    from_dir = load_config_dir(config_dir)
    from_file = load_config_file(out)

    assert from_dir.app.name == from_file.app.name
    assert from_dir.soft_delete.retention_days == from_file.soft_delete.retention_days
    assert from_dir.adapters.repository == from_file.adapters.repository
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
