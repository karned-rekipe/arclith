from pathlib import Path

import pytest
import typer

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
    (config_dir / "adapters.yaml").write_text("logger: console\nrepository: memory\n", encoding="utf-8")
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


def test_add_mongodb_adapter_uses_non_interactive_params(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    add_adapter_cmd(
        project_dir=project_dir,
        adapter="mongodb",
        entity_names=["Widget"],
        activate=False,
        db_name="demo_shared",
        multitenant=True,
        yes=True,
    )

    mongodb_config = (project_dir / "config" / "adapters" / "outbound" / "mongodb.yaml").read_text(
        encoding="utf-8"
    )
    assert "multitenant: true" in mongodb_config
    assert "db_name: demo_shared" in mongodb_config
    assert "repository: memory" in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )


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
    assert "observability: langsmith" in (
        project_dir / "config" / "adapters" / "adapters.yaml"
    ).read_text(encoding="utf-8")

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


def test_boolean_string_default_false_is_false(tmp_path: Path) -> None:
    parameter = ParameterSpec(name="multitenant", kind="boolean", prompt="multitenant", default="false")

    assert _resolve_parameter(parameter, None, tmp_path, prompt_missing=False) is False


def test_non_interactive_requires_entity_when_multiple_models(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    _write_model(project_dir, "demo_service", "Recipe", "recipe")

    with pytest.raises(typer.Exit):
        add_adapter_cmd(project_dir=project_dir, adapter="memory", yes=True)
