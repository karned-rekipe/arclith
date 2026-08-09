import subprocess
import sys
from pathlib import Path

import pytest
import typer
import yaml

from arclith_cli.add_adapter import _resolve_parameter, add_adapter_cmd
from arclith_cli.capabilities import ParameterSpec


def _write_model(project_dir: Path, package_name: str, class_name: str, file_name: str) -> None:
    model_dir = project_dir / "src" / package_name / "domain" / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / f"{file_name}.py").write_text(
        "from arclith.domain.models.entity import Entity\n\n"
        f"class {class_name}(Entity):\n"
        "    pass\n",
        encoding="utf-8",
    )


def _minimal_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "demo-service"
    package_name = "demo_service"
    _write_model(project_dir, package_name, "Widget", "widget")
    (project_dir / "src" / package_name / "adapters" / "outbound").mkdir(parents=True)
    (project_dir / "src" / package_name / "infrastructure" / "containers").mkdir(parents=True)
    config_dir = project_dir / "config" / "adapters"
    config_dir.mkdir(parents=True)
    (config_dir / "adapters.yaml").write_text(
        "logger: console\nrepository: memory\nobservability:\n  enabled: []\n",
        encoding="utf-8",
    )
    return project_dir


def test_add_duckdb_adapter_non_interactive(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    add_adapter_cmd(
        project_dir=project_dir,
        adapter="duckdb",
        duckdb_path="data/widgets.parquet",
        yes=True,
    )

    package_root = project_dir / "src" / "demo_service"
    assert (package_root / "adapters" / "outbound" / "duckdb" / "repositories" / "widget_repository.py").exists()
    assert (package_root / "adapters" / "outbound" / "duckdb" / "repository.py").exists()
    assert 'register("duckdb", _build_duckdb)' in (
        package_root / "infrastructure" / "containers" / "widget_container.py"
    ).read_text(encoding="utf-8")
    assert "repository: duckdb" in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    assert "path: data/widgets.parquet" in (
        project_dir / "config" / "adapters" / "outbound" / "duckdb.yaml"
    ).read_text(encoding="utf-8")


def test_add_duckdb_adapter_generates_loadable_directory_config_idempotently(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    for _ in range(2):
        add_adapter_cmd(
            project_dir=project_dir,
            adapter="duckdb",
            duckdb_path="data/",
            yes=True,
        )

    from arclith import Arclith

    app = Arclith(project_dir / "config")
    duckdb_config = (project_dir / "config" / "adapters" / "outbound" / "duckdb.yaml").read_text(
        encoding="utf-8"
    )
    container = (
        project_dir / "src" / "demo_service" / "infrastructure" / "containers" / "widget_container.py"
    ).read_text(encoding="utf-8")

    assert app.config.adapters.repository == "duckdb"
    assert app.config.adapters.duckdb is not None
    assert app.config.adapters.duckdb.path == "data/"
    assert duckdb_config == "multitenant: false\npath: data/\n"
    assert container.count('register("duckdb", _build_duckdb)') == 1


def test_add_mongodb_adapter_uses_non_interactive_params(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    add_adapter_cmd(
        project_dir=project_dir,
        adapter="mongodb",
        entity_names=["Widget"],
        activate=False,
        db_name="demo_shared",
        adapter_params={"collection_name": "widgets"},
        multitenant=True,
        yes=True,
    )

    mongodb_config = (project_dir / "config" / "adapters" / "outbound" / "mongodb.yaml").read_text(
        encoding="utf-8"
    )
    assert "uri: null" in mongodb_config
    assert "multitenant: true" in mongodb_config
    assert "db_name: demo_shared" in mongodb_config
    assert "collection_name: widgets" in mongodb_config
    secrets = (project_dir / "config" / "secrets.yaml").read_text(encoding="utf-8")
    assert "resolver: env" in secrets
    assert "adapters.mongodb.uri: MONGODB_URI" in secrets
    assert "mongodb://" not in secrets
    assert "repository: memory" in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )


def test_add_mongodb_adapter_generates_loadable_single_tenant_config(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    add_adapter_cmd(
        project_dir=project_dir,
        adapter="mongodb",
        entity_names=["Widget"],
        db_name="demo_shared",
        yes=True,
    )

    from arclith import Arclith

    app = Arclith(project_dir / "config")

    assert app.config.adapters.repository == "mongodb"
    assert app.config.adapters.mongodb is not None
    assert app.config.adapters.mongodb.uri is None
    assert app.config.adapters.mongodb.db_name == "demo_shared"
    assert app.config.adapters.mongodb.collection_name is None
    assert app.config.adapters.mongodb.multitenant is False


def test_add_mariadb_adapter_uses_catalog_params(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    add_adapter_cmd(
        project_dir=project_dir,
        adapter="mariadb",
        adapter_params={
            "host": "mariadb.local",
            "port": "3307",
            "database": "demo_shared",
            "user": "demo_app",
            "driver": "asyncmy",
            "table_prefix": "todo_",
        },
        yes=True,
    )

    package_root = project_dir / "src" / "demo_service"
    repository_file = package_root / "adapters" / "outbound" / "mariadb" / "repositories" / "widget_repository.py"
    assert repository_file.exists()
    assert "class MariaDBWidgetRepository" in repository_file.read_text(encoding="utf-8")
    assert 'register("mariadb", _build_mariadb)' in (
        package_root / "infrastructure" / "containers" / "widget_container.py"
    ).read_text(encoding="utf-8")
    mariadb_config = (project_dir / "config" / "adapters" / "outbound" / "mariadb.yaml").read_text(
        encoding="utf-8"
    )
    assert "host: mariadb.local" in mariadb_config
    assert "port: 3307" in mariadb_config
    assert "database: demo_shared" in mariadb_config
    assert 'table_prefix: "todo_"' in mariadb_config


def test_add_langsmith_observability_adapter_uses_catalog_params(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    (project_dir / ".env").write_text("EXISTING=value\nLANGSMITH_PROJECT=old\n", encoding="utf-8")

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="observability",
        adapter="langsmith",
        adapter_params={
            "tracing": "true",
            "project": "agent-tests",
            "endpoint": "https://eu.api.smith.langchain.com",
            "api_key": "test-key",
        },
        yes=True,
    )

    config = (project_dir / "config" / "adapters" / "outbound" / "langsmith.yaml").read_text(
        encoding="utf-8"
    )
    assert "tracing: true" in config
    assert 'project: "agent-tests"' in config
    assert 'endpoint: "https://eu.api.smith.langchain.com"' in config
    assert "api_key_env: LANGSMITH_API_KEY" in config
    assert 'langgraph_api_min_version: "0.11.0"' in config
    adapters_config = yaml.safe_load(
        (project_dir / "config" / "adapters" / "adapters.yaml").read_text(encoding="utf-8")
    )
    assert adapters_config["observability"]["enabled"] == ["langsmith"]

    env = (project_dir / ".env").read_text(encoding="utf-8")
    assert "EXISTING=value" in env
    assert "LANGSMITH_TRACING=true" in env
    assert "LANGSMITH_PROJECT=agent-tests" in env
    assert "LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com" in env
    assert "LANGSMITH_API_KEY=test-key" in env
    assert ".env" in (project_dir / ".gitignore").read_text(encoding="utf-8")
    package_root = project_dir / "src" / "demo_service"
    assert not (package_root / "adapters" / "outbound" / "langsmith").exists()


def test_add_langsmith_preserves_existing_api_key_when_missing(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    (project_dir / ".env").write_text(
        "LANGSMITH_API_KEY=existing-key\nLANGSMITH_PROJECT = old-project\n",
        encoding="utf-8",
    )

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="observability",
        adapter="langsmith",
        adapter_params={
            "project": "agent-tests",
            "endpoint": "https://api.smith.langchain.com",
        },
        yes=True,
    )

    env = (project_dir / ".env").read_text(encoding="utf-8")
    assert "LANGSMITH_API_KEY=existing-key" in env
    assert "LANGSMITH_PROJECT=agent-tests" in env
    assert "LANGSMITH_PROJECT = old-project" not in env
    assert env.count("LANGSMITH_PROJECT") == 1


def test_add_langsmith_skips_missing_empty_api_key(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="observability",
        adapter="langsmith",
        adapter_params={
            "project": "agent-tests",
            "endpoint": "https://api.smith.langchain.com",
        },
        yes=True,
    )

    env = (project_dir / ".env").read_text(encoding="utf-8")
    assert "LANGSMITH_API_KEY=" not in env
    assert "LANGSMITH_PROJECT=agent-tests" in env


def test_add_fastapi_api_adapter_generates_inbound_config_only(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="api",
        adapter="fastapi",
        adapter_params={
            "host": "127.0.0.1",
            "port": "8080",
            "reload": "false",
        },
        yes=True,
    )

    config = (project_dir / "config" / "adapters" / "inbound" / "fastapi.yaml").read_text(
        encoding="utf-8"
    )
    assert "host: 127.0.0.1" in config
    assert "port: 8080" in config
    assert "reload: false" in config
    assert "repository: memory" in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    package_root = project_dir / "src" / "demo_service"
    assert not (package_root / "adapters" / "outbound" / "fastapi").exists()


def test_add_fastmcp_mcp_adapter_generates_inbound_config_only(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="mcp",
        adapter="fastmcp",
        adapter_params={
            "host": "127.0.0.1",
            "port": "9001",
        },
        yes=True,
    )

    config = (project_dir / "config" / "adapters" / "inbound" / "fastmcp.yaml").read_text(
        encoding="utf-8"
    )
    assert "host: 127.0.0.1" in config
    assert "port: 9001" in config
    assert "repository: memory" in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    package_root = project_dir / "src" / "demo_service"
    assert not (package_root / "adapters" / "outbound" / "fastmcp").exists()


def test_add_lmstudio_llm_adapter_generates_lm_config_only(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="llm",
        adapter="lmstudio",
        adapter_params={
            "model_name": "qwen/qwen3.5-9b",
            "base_url": "http://127.0.0.1:1234/v1",
            "api_key": "lm-studio",
        },
        yes=True,
    )

    config = (project_dir / "config" / "adapters" / "outbound" / "lm.yaml").read_text(
        encoding="utf-8"
    )
    assert "provider: openai" in config
    assert 'model_name: "qwen/qwen3.5-9b"' in config
    assert 'api_key: "lm-studio"' in config
    assert 'base_url: "http://127.0.0.1:1234/v1"' in config
    assert "repository: memory" in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    assert not (project_dir / "config" / "secrets.yaml").exists()

    package_root = project_dir / "src" / "demo_service"
    assert not (package_root / "adapters" / "outbound" / "lmstudio").exists()


def test_add_openai_llm_adapter_generates_secret_mapping(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    (project_dir / ".env").write_text("EXISTING=value\n", encoding="utf-8")

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="llm",
        adapter="openai",
        adapter_params={
            "model_name": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
        },
        yes=True,
    )

    config = (project_dir / "config" / "adapters" / "outbound" / "lm.yaml").read_text(
        encoding="utf-8"
    )
    assert "provider: openai" in config
    assert 'model_name: "gpt-4o-mini"' in config
    assert 'api_key: ""' in config
    assert 'base_url: "https://api.openai.com/v1"' in config

    secrets = (project_dir / "config" / "secrets.yaml").read_text(encoding="utf-8")
    assert "resolver: env" in secrets
    assert "adapters.lm.api_key: OPENAI_API_KEY" in secrets

    env = (project_dir / ".env").read_text(encoding="utf-8")
    assert "EXISTING=value" in env
    assert "OPENAI_API_KEY=sk-test" in env
    assert ".env" in (project_dir / ".gitignore").read_text(encoding="utf-8")
    assert "llm:" not in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )


def test_add_opentelemetry_observability_adapter_uses_catalog_params(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    (project_dir / ".env").write_text("EXISTING=value\n", encoding="utf-8")

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="observability",
        adapter="opentelemetry",
        adapter_params={
            "service_name": "demo-api",
            "endpoint": "http://otel-collector:4318",
            "traces_endpoint": "http://otel-collector:4318/custom/traces",
            "metrics_endpoint": "http://otel-collector:4318/custom/metrics",
            "protocol": "http/protobuf",
            "traces": "true",
            "metrics": "true",
            "instrument_fastapi": "true",
            "metrics_export_interval_millis": "15000",
            "headers": "authorization=Bearer test",
        },
        yes=True,
    )

    config = (project_dir / "config" / "adapters" / "outbound" / "opentelemetry.yaml").read_text(
        encoding="utf-8"
    )
    assert 'service_name: "demo-api"' in config
    assert 'endpoint: "http://otel-collector:4318"' in config
    assert "traces_endpoint: http://otel-collector:4318/custom/traces" in config
    assert "metrics_endpoint: http://otel-collector:4318/custom/metrics" in config
    assert 'protocol: "http/protobuf"' in config
    assert "headers_env: OTEL_EXPORTER_OTLP_HEADERS" in config
    assert "traces: true" in config
    assert "metrics: true" in config
    assert "instrument_fastapi: true" in config
    assert "metrics_export_interval_millis: 15000" in config
    adapters_config = yaml.safe_load(
        (project_dir / "config" / "adapters" / "adapters.yaml").read_text(encoding="utf-8")
    )
    assert adapters_config["observability"]["enabled"] == ["opentelemetry"]

    env = (project_dir / ".env").read_text(encoding="utf-8")
    assert "EXISTING=value" in env
    assert "OTEL_SERVICE_NAME=demo-api" in env
    assert "OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318" in env
    assert "OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf" in env
    assert "OTEL_EXPORTER_OTLP_HEADERS=authorization=Bearer test" in env
    assert ".env" in (project_dir / ".gitignore").read_text(encoding="utf-8")


def test_add_observability_adapters_accumulates_enabled_backends(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="observability",
        adapter="langsmith",
        adapter_params={"project": "agent-tests"},
        yes=True,
    )
    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="observability",
        adapter="opentelemetry",
        adapter_params={"service_name": "demo-api"},
        yes=True,
    )

    adapters_config = yaml.safe_load(
        (project_dir / "config" / "adapters" / "adapters.yaml").read_text(encoding="utf-8")
    )
    assert adapters_config["observability"]["enabled"] == ["langsmith", "opentelemetry"]

    config = (project_dir / "config" / "adapters" / "outbound" / "opentelemetry.yaml").read_text(
        encoding="utf-8"
    )
    assert "traces_endpoint: null" in config
    assert "metrics_endpoint: null" in config


def test_add_langgraph_agent_adapter_generates_runtime_entrypoint(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="agent",
        adapter="langgraph",
        adapter_params={"graph_name": "todo_agent"},
        yes=True,
    )

    package_root = project_dir / "src" / "demo_service"
    langgraph_json = (project_dir / "langgraph.json").read_text(encoding="utf-8")
    langgraph_config = (project_dir / "config" / "adapters" / "inbound" / "langgraph.yaml").read_text(
        encoding="utf-8"
    )
    agent_file = package_root / "adapters" / "inbound" / "langgraph" / "agent.py"

    assert (project_dir / "config" / "adapters" / "inbound" / "langgraph.yaml").exists()
    assert (package_root / "adapters" / "inbound" / "langgraph" / "__init__.py").exists()
    assert agent_file.exists()
    assert '"todo_agent": "./src/demo_service/adapters/inbound/langgraph/agent.py:agent"' in langgraph_json
    adapters_yaml = (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    assert "repository: memory" in adapters_yaml
    assert "agent:" not in adapters_yaml
    assert 'name: "todo_agent"' in langgraph_config
    assert 'entrypoint: "./src/demo_service/adapters/inbound/langgraph/agent.py:agent"' in langgraph_config
    assert "agent = arclith.langgraph(AgentState, register_agent, name=\"todo_agent\")" in agent_file.read_text(
        encoding="utf-8"
    )
    assert not (package_root / "adapters" / "outbound" / "langgraph").exists()


def test_add_non_entity_adapter_rejects_entity_selection(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    with pytest.raises(typer.Exit):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="agent",
            adapter="langgraph",
            entity_names=["Widget"],
            yes=True,
        )


def test_add_transport_adapter_rejects_entity_selection(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    with pytest.raises(typer.Exit):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="api",
            adapter="fastapi",
            entity_names=["Widget"],
            yes=True,
        )


def test_add_adapter_rejects_unknown_catalog_param(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    with pytest.raises(typer.Exit):
        add_adapter_cmd(
            project_dir=project_dir,
            adapter="mariadb",
            adapter_params={"database": "demo", "unknown": "value"},
            yes=True,
        )


def test_add_memory_adapter_rejects_unknown_catalog_param(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    with pytest.raises(typer.Exit):
        add_adapter_cmd(
            project_dir=project_dir,
            adapter="memory",
            adapter_params={"unused": "value"},
            yes=True,
        )


def test_add_memory_adapter_direct_cli_keeps_memory_and_loads_config(tmp_path: Path) -> None:
    project_dir = tmp_path / "memory-service"

    result = subprocess.run(
        [
            "arclith-cli",
            "init",
            "memory-service",
            "--dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"init failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

    result = subprocess.run(
        ["arclith-cli", "add-entity", "Widget"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"add-entity failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

    result = subprocess.run(
        [
            "arclith-cli",
            "add-adapter",
            "--capability",
            "repository",
            "--adapter",
            "memory",
            "--entity",
            "Widget",
            "--yes",
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"add-adapter failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

    package_root = project_dir / "src" / "memory_service"
    assert (package_root / "adapters" / "outbound" / "memory" / "repositories" / "widget_repository.py").exists()
    assert (package_root / "adapters" / "outbound" / "memory" / "repository.py").exists()
    assert not (project_dir / "config" / "adapters" / "outbound" / "memory.yaml").exists()

    adapters_config = yaml.safe_load(
        (project_dir / "config" / "adapters" / "adapters.yaml").read_text(encoding="utf-8")
    )
    assert adapters_config["repository"] == "memory"

    load_result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from arclith import Arclith\n"
                "app = Arclith('config')\n"
                "assert app.config.adapters.repository == 'memory'\n"
                "print(app.config.adapters.repository)\n"
            ),
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert load_result.returncode == 0, (
        f"Arclith config load failed:\nSTDOUT:\n{load_result.stdout}\nSTDERR:\n{load_result.stderr}"
    )
    assert load_result.stdout.strip() == "memory"


def test_add_memory_adapter_interactive_wizard_activates_memory(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    result = subprocess.run(
        ["arclith-cli", "add-adapter"],
        cwd=project_dir,
        input="1\ny\ny\n",
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, f"wizard failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    package_root = project_dir / "src" / "demo_service"
    assert (package_root / "adapters" / "outbound" / "memory" / "repositories" / "widget_repository.py").exists()
    assert "repository: memory" in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )


def test_boolean_string_default_false_is_false(tmp_path: Path) -> None:
    parameter = ParameterSpec(name="multitenant", kind="boolean", prompt="multitenant", default="false")

    assert _resolve_parameter(parameter, None, tmp_path, prompt_missing=False) is False


def test_non_interactive_requires_entity_when_multiple_models(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    _write_model(project_dir, "demo_service", "Recipe", "recipe")

    with pytest.raises(typer.Exit):
        add_adapter_cmd(project_dir=project_dir, adapter="memory", yes=True)
