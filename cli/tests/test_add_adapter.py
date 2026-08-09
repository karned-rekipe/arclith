import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

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
    assert "url: null" in mariadb_config
    assert "password: null" in mariadb_config
    assert 'table_prefix: "todo_"' in mariadb_config

    secrets = (project_dir / "config" / "secrets.yaml").read_text(encoding="utf-8")
    assert "resolver: env" in secrets
    assert "adapters.mariadb.url: MARIADB_URL" in secrets
    assert "adapters.mariadb.password: MARIADB_PASSWORD" in secrets
    assert "secret-password" not in mariadb_config
    assert "secret-password" not in secrets


@pytest.mark.parametrize("secret_param", ["password", "url"])
def test_add_mariadb_adapter_rejects_direct_secret_params(tmp_path: Path, secret_param: str) -> None:
    project_dir = _minimal_project(tmp_path)

    with pytest.raises(typer.Exit):
        add_adapter_cmd(
            project_dir=project_dir,
            adapter="mariadb",
            adapter_params={
                "database": "demo_shared",
                secret_param: "secret-password",
            },
            yes=True,
        )

    assert not (project_dir / "config" / "adapters" / "outbound" / "mariadb.yaml").exists()
    assert not (project_dir / "config" / "secrets.yaml").exists()


def test_add_langsmith_observability_adapter_uses_catalog_params(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
    cli_output = capsys.readouterr()

    config = (project_dir / "config" / "adapters" / "outbound" / "langsmith.yaml").read_text(
        encoding="utf-8"
    )
    assert "tracing: true" in config
    assert 'project: "agent-tests"' in config
    assert 'endpoint: "https://eu.api.smith.langchain.com"' in config
    assert "api_key_env: LANGSMITH_API_KEY" in config
    assert "Définir LANGSMITH_API_KEY hors Git" in config
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
    assert "test-key" not in cli_output.out
    assert "test-key" not in cli_output.err
    from arclith import Arclith

    arclith = Arclith(project_dir / "config")
    load_output = capsys.readouterr()

    assert arclith.config.adapters.observability.enabled == ["langsmith"]
    assert arclith.config.adapters.langsmith is not None
    assert arclith.config.adapters.langsmith.tracing is True
    assert arclith.config.adapters.langsmith.project == "agent-tests"
    assert arclith.config.adapters.langsmith.endpoint == "https://eu.api.smith.langchain.com"
    assert "test-key" not in load_output.out
    assert "test-key" not in load_output.err
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
    config = (project_dir / "config" / "adapters" / "outbound" / "langsmith.yaml").read_text(
        encoding="utf-8"
    )
    assert "LANGSMITH_API_KEY=" not in env
    assert "LANGSMITH_PROJECT=agent-tests" in env
    assert "api_key_env: LANGSMITH_API_KEY" in config
    assert "Définir LANGSMITH_API_KEY hors Git" in config


def test_add_fastapi_api_adapter_generates_inbound_config_only(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    config_path = project_dir / "config" / "adapters" / "inbound" / "fastapi.yaml"

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
    first_config = config_path.read_text(encoding="utf-8")

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
    second_config = config_path.read_text(encoding="utf-8")
    config = yaml.safe_load(second_config)

    assert second_config == first_config
    assert config == {"host": "127.0.0.1", "port": 8080, "reload": False}
    assert "repository: memory" in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    package_root = project_dir / "src" / "demo_service"
    assert not (package_root / "adapters" / "outbound" / "fastapi").exists()
    assert not (package_root / "adapters" / "inbound" / "fastapi").exists()

    from arclith import Arclith

    arclith = Arclith(project_dir / "config")
    app = arclith.fastapi()

    assert arclith.config.api.host == "127.0.0.1"
    assert arclith.config.api.port == 8080
    assert arclith.config.api.reload is False
    assert app.title == arclith.config.app.name


def test_add_fastmcp_mcp_adapter_generates_inbound_config_only(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    config_path = project_dir / "config" / "adapters" / "inbound" / "fastmcp.yaml"

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
    first_config = config_path.read_text(encoding="utf-8")

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
    second_config = config_path.read_text(encoding="utf-8")
    config = yaml.safe_load(second_config)

    assert second_config == first_config
    assert config == {"host": "127.0.0.1", "port": 9001}
    assert "repository: memory" in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    package_root = project_dir / "src" / "demo_service"
    assert not (package_root / "adapters" / "outbound" / "fastmcp").exists()
    assert not (package_root / "adapters" / "inbound" / "fastmcp").exists()

    from arclith import Arclith

    arclith = Arclith(project_dir / "config")
    arclith.fastmcp("demo-service")

    class FakeMcp:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def run(self, **kwargs: object) -> None:
            self.calls.append(kwargs)

    fake_mcp = FakeMcp()
    arclith.run_mcp_sse(fake_mcp)
    arclith.run_mcp_http(fake_mcp)

    assert arclith.config.mcp.host == "127.0.0.1"
    assert arclith.config.mcp.port == 9001
    assert fake_mcp.calls == [
        {"transport": "sse", "host": "127.0.0.1", "port": 9001},
        {"transport": "streamable-http", "host": "127.0.0.1", "port": 9001},
    ]


def test_add_probe_server_adapter_generates_loadable_inbound_config(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="probe",
        adapter="server",
        adapter_params={
            "host": "127.0.0.1",
            "port": "9100",
            "enabled": "false",
        },
        yes=True,
    )

    from arclith import Arclith

    arclith = Arclith(project_dir / "config")
    config = (project_dir / "config" / "adapters" / "inbound" / "probe.yaml").read_text(
        encoding="utf-8"
    )
    package_root = project_dir / "src" / "demo_service"

    assert config == "host: 127.0.0.1\nport: 9100\nenabled: false\n"
    assert arclith.config.probe.host == "127.0.0.1"
    assert arclith.config.probe.port == 9100
    assert arclith.config.probe.enabled is False
    assert "probe:" not in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    assert not (package_root / "adapters" / "inbound" / "server").exists()
    assert not (package_root / "adapters" / "outbound" / "server").exists()


def test_add_http_idempotency_adapter_merges_http_config(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    http_path = project_dir / "config" / "http.yaml"
    http_path.write_text(
        "etag:\n"
        "  enabled: true\n"
        "cache_control:\n"
        "  get_single_max_age: 120\n"
        "  get_list_max_age: 30\n",
        encoding="utf-8",
    )

    for _ in range(2):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="http",
            adapter="idempotency",
            adapter_params={
                "enabled": "false",
                "ttl_seconds": "7200",
                "required": "true",
            },
            yes=True,
        )

    from arclith import Arclith

    config = yaml.safe_load(http_path.read_text(encoding="utf-8"))
    arclith = Arclith(project_dir / "config")
    package_root = project_dir / "src" / "demo_service"

    assert config == {
        "etag": {"enabled": True},
        "cache_control": {"get_single_max_age": 120, "get_list_max_age": 30},
        "idempotency": {"enabled": False, "ttl_seconds": 7200, "required": True},
    }
    assert arclith.config.http.idempotency.enabled is False
    assert arclith.config.http.idempotency.ttl_seconds == 7200
    assert arclith.config.http.idempotency.required is True
    assert "http:" not in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    assert not (package_root / "adapters" / "inbound" / "idempotency").exists()


def test_add_http_etag_adapter_merges_http_config(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    http_path = project_dir / "config" / "http.yaml"
    http_path.write_text(
        "idempotency:\n"
        "  enabled: true\n"
        "  ttl_seconds: 86400\n"
        "  required: true\n"
        "cache_control:\n"
        "  get_single_max_age: 120\n"
        "  get_list_max_age: 30\n",
        encoding="utf-8",
    )

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="http",
        adapter="etag",
        adapter_params={"enabled": "false"},
        yes=True,
    )

    from arclith import Arclith

    config = yaml.safe_load(http_path.read_text(encoding="utf-8"))
    arclith = Arclith(project_dir / "config")
    package_root = project_dir / "src" / "demo_service"

    assert config == {
        "idempotency": {"enabled": True, "ttl_seconds": 86400, "required": True},
        "cache_control": {"get_single_max_age": 120, "get_list_max_age": 30},
        "etag": {"enabled": False},
    }
    assert arclith.config.http.etag.enabled is False
    assert "http:" not in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    assert not (package_root / "adapters" / "inbound" / "etag").exists()


def test_add_http_cache_control_adapter_merges_http_config(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    http_path = project_dir / "config" / "http.yaml"
    http_path.write_text(
        "idempotency:\n"
        "  enabled: true\n"
        "  ttl_seconds: 86400\n"
        "  required: true\n"
        "etag:\n"
        "  enabled: false\n"
        "cache_control:\n"
        "  get_single_max_age: 300\n"
        "  get_list_max_age: 60\n",
        encoding="utf-8",
    )

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="http",
        adapter="cache-control",
        adapter_params={
            "get_single_max_age": "900",
            "get_list_max_age": "0",
        },
        yes=True,
    )

    from arclith import Arclith

    config = yaml.safe_load(http_path.read_text(encoding="utf-8"))
    arclith = Arclith(project_dir / "config")
    package_root = project_dir / "src" / "demo_service"

    assert config == {
        "idempotency": {"enabled": True, "ttl_seconds": 86400, "required": True},
        "etag": {"enabled": False},
        "cache_control": {"get_single_max_age": 900, "get_list_max_age": 0},
    }
    assert arclith.config.http.cache_control.get_single_max_age == 900
    assert arclith.config.http.cache_control.get_list_max_age == 0
    assert "http:" not in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    assert not (package_root / "adapters" / "inbound" / "cache-control").exists()


def test_add_http_cache_control_adapter_rejects_negative_max_age(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    http_path = project_dir / "config" / "http.yaml"

    with pytest.raises(typer.Exit):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="http",
            adapter="cache-control",
            adapter_params={
                "get_single_max_age": "-1",
                "get_list_max_age": "60",
            },
            yes=True,
        )

    assert not http_path.exists()


def test_add_command_bus_rabbitmq_adapter_merges_command_bus_config(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    command_bus_path = project_dir / "config" / "command_bus.yaml"
    command_bus_path.write_text(
        "enabled: []\n"
        "rabbitmq:\n"
        "  url: amqp://old/\n"
        "  exchange: old.exchange\n",
        encoding="utf-8",
    )

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="command-bus",
        adapter="rabbitmq",
        adapter_params={
            "url": "amqp://broker/",
            "exchange": "commands.exchange",
            "exchange_type": "direct",
            "queue": "commands.queue",
            "routing_key": "commands.route",
            "prefetch": "7",
            "consumer_name": "worker-a",
            "concurrency": "2",
            "publisher_confirms": "true",
            "durable": "true",
            "retry_enabled": "true",
            "retry_requeue": "false",
            "dead_letter_exchange": "commands.dlx",
            "dead_letter_routing_key": "commands.dead",
        },
        yes=True,
    )

    from arclith import Arclith

    config = yaml.safe_load(command_bus_path.read_text(encoding="utf-8"))
    arclith = Arclith(project_dir / "config")
    package_root = project_dir / "src" / "demo_service"

    assert config == {
        "enabled": ["rabbitmq"],
        "rabbitmq": {
            "url": "amqp://broker/",
            "exchange": "commands.exchange",
            "exchange_type": "direct",
            "queue": "commands.queue",
            "routing_key": "commands.route",
            "prefetch": 7,
            "consumer_name": "worker-a",
            "concurrency": 2,
            "publisher_confirms": True,
            "durable": True,
            "retry_enabled": True,
            "retry_requeue": False,
            "dead_letter_exchange": "commands.dlx",
            "dead_letter_routing_key": "commands.dead",
        },
    }
    assert arclith.config.command_bus.is_enabled("rabbitmq") is True
    assert arclith.config.command_bus.rabbitmq.prefetch == 7
    assert arclith.config.command_bus.rabbitmq.concurrency == 2
    assert "command-bus:" not in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    assert not (package_root / "adapters" / "bidirectional" / "rabbitmq").exists()


def test_add_command_bus_rabbitmq_adapter_rejects_unbounded_prefetch(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    command_bus_path = project_dir / "config" / "command_bus.yaml"

    with pytest.raises(typer.Exit):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="command-bus",
            adapter="rabbitmq",
            adapter_params={"prefetch": "0"},
            yes=True,
        )

    assert not command_bus_path.exists()


def test_add_keycloak_auth_adapter_generates_loadable_inbound_config(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    config_path = project_dir / "config" / "adapters" / "inbound" / "keycloak.yaml"

    for _ in range(2):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="auth",
            adapter="keycloak",
            adapter_params={
                "url": "https://auth.example.test",
                "realm": "rekipe",
                "audience": "rekipe-api",
                "client_id": "swagger-public",
            },
            yes=True,
        )
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert config == {
        "url": "https://auth.example.test",
        "realm": "rekipe",
        "audience": "rekipe-api",
        "client_id": "swagger-public",
    }
    assert "auth:" not in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    package_root = project_dir / "src" / "demo_service"
    assert not (package_root / "adapters" / "inbound" / "keycloak").exists()

    from arclith import Arclith

    arclith = Arclith(project_dir / "config")

    assert arclith.config.keycloak is not None
    assert arclith.config.keycloak.url == "https://auth.example.test"
    assert arclith.config.keycloak.realm == "rekipe"
    assert arclith.config.keycloak.audience == "rekipe-api"
    assert arclith.config.keycloak.client_id == "swagger-public"


def test_add_vault_tenant_adapter_with_mongodb_multitenant_loads_config(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    cache_path = project_dir / "config" / "adapters" / "inbound" / "cache.yaml"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        "backend: memory\n"
        "jwks_ttl: 1200\n"
        "tenant_uri_ttl: 180\n",
        encoding="utf-8",
    )

    add_adapter_cmd(
        project_dir=project_dir,
        adapter="mongodb",
        activate=True,
        db_name="fallback_db",
        adapter_params={"collection_name": "widgets"},
        multitenant=True,
        yes=True,
    )
    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="tenant",
        adapter="vault",
        adapter_params={
            "addr": "http://vault:8200",
            "mount": "kv-tenants",
            "path_prefix": "rekipe/tenants",
            "tenant_claim": "tenant_id",
            "tenant_uri_ttl": "45",
        },
        yes=True,
    )

    from arclith import Arclith

    arclith = Arclith(project_dir / "config")
    tenant_config = (project_dir / "config" / "adapters" / "inbound" / "tenant.yaml").read_text(
        encoding="utf-8"
    )
    cache_config = yaml.safe_load(cache_path.read_text(encoding="utf-8"))

    assert arclith.config.adapters.repository == "mongodb"
    assert arclith.config.adapters.mongodb is not None
    assert arclith.config.adapters.mongodb.multitenant is True
    assert arclith.config.tenant is not None
    assert arclith.config.tenant.vault_addr == "http://vault:8200"
    assert arclith.config.tenant.vault_mount == "kv-tenants"
    assert arclith.config.tenant.vault_path_prefix == "rekipe/tenants"
    assert arclith.config.tenant.tenant_claim == "tenant_id"
    assert arclith.config.cache.backend == "memory"
    assert arclith.config.cache.jwks_ttl == 1200
    assert arclith.config.cache.tenant_uri_ttl == 45
    assert cache_config == {"backend": "memory", "jwks_ttl": 1200, "tenant_uri_ttl": 45}
    assert 'vault_addr: "http://vault:8200"' in tenant_config


def test_add_role_license_adapter_generates_loadable_config(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    config_path = project_dir / "config" / "adapters" / "inbound" / "license.yaml"

    for _ in range(2):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="license",
            adapter="role",
            adapter_params={"role": "rekipe:premium"},
            yes=True,
        )
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert config == {"role": "rekipe:premium"}
    assert "license:" not in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    package_root = project_dir / "src" / "demo_service"
    assert not (package_root / "adapters" / "inbound" / "role").exists()
    assert not (package_root / "adapters" / "outbound" / "role").exists()

    from arclith import Arclith

    arclith = Arclith(project_dir / "config")

    assert arclith.config.license is not None
    assert arclith.config.license.role == "rekipe:premium"


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

    from arclith import Arclith

    arclith = Arclith(project_dir / "config")

    assert arclith.config.adapters.lm is not None
    assert arclith.config.adapters.lm.provider == "openai"
    assert arclith.config.adapters.lm.model_name == "qwen/qwen3.5-9b"
    assert arclith.config.adapters.lm.api_key == "lm-studio"
    assert arclith.config.adapters.lm.base_url == "http://127.0.0.1:1234/v1"


def test_add_openai_llm_adapter_generates_secret_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
    captured = capsys.readouterr()

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
    assert "sk-test" not in captured.out
    assert "sk-test" not in captured.err

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from arclith import Arclith

    arclith = Arclith(project_dir / "config")

    assert arclith.config.adapters.lm is not None
    assert arclith.config.adapters.lm.provider == "openai"
    assert arclith.config.adapters.lm.model_name == "gpt-4o-mini"
    assert arclith.config.adapters.lm.api_key == "sk-test"
    assert arclith.config.adapters.lm.base_url == "https://api.openai.com/v1"


def test_add_openai_llm_adapter_without_key_does_not_generate_fake_secret(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_dir = _minimal_project(tmp_path)
    (project_dir / ".env").write_text("EXISTING=value\n", encoding="utf-8")

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="llm",
        adapter="openai",
        adapter_params={
            "model_name": "custom-openai-model",
            "base_url": "https://api.openai.com/v1",
        },
        yes=True,
    )
    captured = capsys.readouterr()

    env = (project_dir / ".env").read_text(encoding="utf-8")
    config = (project_dir / "config" / "adapters" / "outbound" / "lm.yaml").read_text(
        encoding="utf-8"
    )

    assert "EXISTING=value" in env
    assert "OPENAI_API_KEY=" not in env
    assert "sk-" not in env
    assert 'api_key: ""' in config
    assert "adapters.lm.api_key: OPENAI_API_KEY" in (
        project_dir / "config" / "secrets.yaml"
    ).read_text(encoding="utf-8")
    assert "sk-" not in captured.out
    assert "sk-" not in captured.err


def test_add_anthropic_llm_adapter_generates_idempotent_secret_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_dir = _minimal_project(tmp_path)
    (project_dir / ".env").write_text(
        "EXISTING=value\nANTHROPIC_API_KEY=existing-local-key\n",
        encoding="utf-8",
    )
    (project_dir / "config" / "secrets.yaml").write_text(
        "resolver: env\nmappings:\n  adapters.lm.api_key: ANTHROPIC_API_KEY\n",
        encoding="utf-8",
    )

    for _ in range(2):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="llm",
            adapter="anthropic",
            adapter_params={
                "model_name": "claude-dev-model",
            },
            yes=True,
        )
    captured = capsys.readouterr()

    config = (project_dir / "config" / "adapters" / "outbound" / "lm.yaml").read_text(
        encoding="utf-8"
    )
    env = (project_dir / ".env").read_text(encoding="utf-8")
    secrets = yaml.safe_load((project_dir / "config" / "secrets.yaml").read_text(encoding="utf-8"))

    assert "provider: anthropic" in config
    assert 'model_name: "claude-dev-model"' in config
    assert 'api_key: ""' in config
    assert env.count("ANTHROPIC_API_KEY=existing-local-key") == 1
    assert "EXISTING=value" in env
    assert secrets["resolver"] == "env"
    assert secrets["mappings"]["adapters.lm.api_key"] == "ANTHROPIC_API_KEY"
    assert list(secrets["mappings"]).count("adapters.lm.api_key") == 1
    assert "llm:" not in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    assert "existing-local-key" not in captured.out
    assert "existing-local-key" not in captured.err

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from arclith import Arclith

    arclith = Arclith(project_dir / "config")

    assert arclith.config.adapters.lm is not None
    assert arclith.config.adapters.lm.provider == "anthropic"
    assert arclith.config.adapters.lm.model_name == "claude-dev-model"
    assert arclith.config.adapters.lm.api_key == "sk-ant-test"


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


def test_add_langsmith_preserves_existing_opentelemetry_activation(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    (project_dir / ".env").write_text("EXISTING=value\n", encoding="utf-8")

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="observability",
        adapter="opentelemetry",
        adapter_params={"service_name": "demo-api"},
        yes=True,
    )
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
        adapter="langsmith",
        adapter_params={"project": "agent-tests"},
        yes=True,
    )

    adapters_config = yaml.safe_load(
        (project_dir / "config" / "adapters" / "adapters.yaml").read_text(encoding="utf-8")
    )
    env = (project_dir / ".env").read_text(encoding="utf-8")
    opentelemetry_config = (
        project_dir / "config" / "adapters" / "outbound" / "opentelemetry.yaml"
    ).read_text(encoding="utf-8")

    assert adapters_config["observability"]["enabled"] == ["opentelemetry", "langsmith"]
    assert adapters_config["observability"]["enabled"].count("langsmith") == 1
    assert adapters_config["observability"]["enabled"].count("opentelemetry") == 1
    assert "EXISTING=value" in env
    assert "OTEL_SERVICE_NAME=demo-api" in env
    assert "LANGSMITH_PROJECT=agent-tests" in env
    assert "LANGSMITH_API_KEY=" not in env
    assert 'service_name: "demo-api"' in opentelemetry_config


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
    langgraph_json = json.loads((project_dir / "langgraph.json").read_text(encoding="utf-8"))
    langgraph_config = (project_dir / "config" / "adapters" / "inbound" / "langgraph.yaml").read_text(
        encoding="utf-8"
    )
    agent_file = package_root / "adapters" / "inbound" / "langgraph" / "agent.py"

    assert (project_dir / "config" / "adapters" / "inbound" / "langgraph.yaml").exists()
    assert (package_root / "adapters" / "inbound" / "langgraph" / "__init__.py").exists()
    assert agent_file.exists()
    assert langgraph_json["graphs"] == {
        "todo_agent": "./src/demo_service/adapters/inbound/langgraph/agent.py:agent"
    }
    assert langgraph_json["dependencies"] == ["."]
    assert langgraph_json["env"] == ".env"
    adapters_yaml = (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    assert "repository: memory" in adapters_yaml
    assert "agent:" not in adapters_yaml
    assert 'name: "todo_agent"' in langgraph_config
    assert 'entrypoint: "./src/demo_service/adapters/inbound/langgraph/agent.py:agent"' in langgraph_config
    generated_agent = agent_file.read_text(encoding="utf-8")
    assert "Template minimal volontaire" in generated_agent
    assert "agent = arclith.langgraph(AgentState, register_agent, name=\"todo_agent\")" in generated_agent
    assert not (package_root / "adapters" / "outbound" / "langgraph").exists()


@pytest.mark.asyncio
async def test_add_langgraph_agent_adapter_generates_compilable_minimal_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("langgraph.graph")
    project_dir = _minimal_project(tmp_path)

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="agent",
        adapter="langgraph",
        adapter_params={"graph_name": "todo_agent"},
        yes=True,
    )

    agent_file = project_dir / "src" / "demo_service" / "adapters" / "inbound" / "langgraph" / "agent.py"
    monkeypatch.chdir(project_dir)
    monkeypatch.syspath_prepend(str(project_dir / "src"))
    spec = importlib.util.spec_from_file_location(
        "demo_service.adapters.inbound.langgraph.agent",
        agent_file,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        assert await module.agent.ainvoke({"messages": []}) == {"messages": []}
    finally:
        sys.modules.pop(spec.name, None)


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


def test_add_cache_adapter_rejects_entity_selection(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    with pytest.raises(typer.Exit):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="cache",
            adapter="memory",
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


def test_add_cache_memory_adapter_generates_loadable_config(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="cache",
        adapter="memory",
        adapter_params={
            "jwks_ttl": "1200",
            "tenant_uri_ttl": "180",
        },
        yes=True,
    )

    from arclith import Arclith
    from arclith.adapters.outbound.memory.cache_adapter import MemoryCacheAdapter

    cache_config = (project_dir / "config" / "adapters" / "inbound" / "cache.yaml").read_text(
        encoding="utf-8"
    )
    app = Arclith(project_dir / "config")

    assert cache_config == "backend: memory\njwks_ttl: 1200\ntenant_uri_ttl: 180\n"
    assert app.config.cache.backend == "memory"
    assert app.config.cache.jwks_ttl == 1200
    assert app.config.cache.tenant_uri_ttl == 180
    assert isinstance(app._cache, MemoryCacheAdapter)


def test_add_cache_redis_adapter_generates_secret_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_dir = _minimal_project(tmp_path)
    (project_dir / ".env").write_text("EXISTING=value\n", encoding="utf-8")

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="cache",
        adapter="redis",
        adapter_params={
            "redis_url": "redis://cache:6379/0",
            "jwks_ttl": "900",
            "tenant_uri_ttl": "120",
        },
        yes=True,
    )
    captured = capsys.readouterr()

    cache_config = (project_dir / "config" / "adapters" / "inbound" / "cache.yaml").read_text(
        encoding="utf-8"
    )
    secrets = yaml.safe_load((project_dir / "config" / "secrets.yaml").read_text(encoding="utf-8"))
    env = (project_dir / ".env").read_text(encoding="utf-8")

    assert cache_config == 'backend: redis\nredis_url: ""\njwks_ttl: 900\ntenant_uri_ttl: 120\n'
    assert secrets["resolver"] == "env"
    assert secrets["mappings"]["cache.redis_url"] == "REDIS_URL"
    assert "EXISTING=value" in env
    assert "REDIS_URL=redis://cache:6379/0" in env
    assert "cache:" not in (project_dir / "config" / "adapters" / "adapters.yaml").read_text(
        encoding="utf-8"
    )
    assert "redis://cache:6379/0" not in cache_config
    assert "redis://cache:6379/0" not in (project_dir / "config" / "secrets.yaml").read_text(
        encoding="utf-8"
    )
    assert "redis://cache:6379/0" not in captured.out
    assert "redis://cache:6379/0" not in captured.err

    monkeypatch.setenv("REDIS_URL", "redis://cache:6379/0")
    from arclith import Arclith

    app = Arclith(project_dir / "config")

    assert app.config.cache.backend == "redis"
    assert app.config.cache.redis_url == "redis://cache:6379/0"
    assert app.config.cache.jwks_ttl == 900
    assert app.config.cache.tenant_uri_ttl == 120


def test_add_console_logger_adapter_generates_explicit_default_selector(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    adapters_path = project_dir / "config" / "adapters" / "adapters.yaml"
    adapters_path.write_text("repository: memory\nobservability:\n  enabled: []\n", encoding="utf-8")

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="logger",
        adapter="console",
        yes=True,
    )

    from arclith import Arclith
    from arclith.adapters.outbound.console.logger import ConsoleLogger

    arclith = Arclith(project_dir / "config")
    package_root = project_dir / "src" / "demo_service"

    assert "logger: console" in adapters_path.read_text(encoding="utf-8")
    assert arclith.config.adapters.logger == "console"
    assert isinstance(arclith.logger, ConsoleLogger)
    assert not (package_root / "adapters" / "outbound" / "console").exists()


def test_add_env_secrets_adapter_preserves_existing_mappings_and_uses_explicit_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _minimal_project(tmp_path)
    (project_dir / "config" / "secrets.yaml").write_text(
        "resolver: yaml\n"
        "mappings:\n"
        "  adapters.lm.api_key: OPENAI_API_KEY\n",
        encoding="utf-8",
    )
    outbound_dir = project_dir / "config" / "adapters" / "outbound"
    outbound_dir.mkdir(parents=True, exist_ok=True)
    (outbound_dir / "mongodb.yaml").write_text(
        "uri: null\n"
        "db_name: demo\n"
        "collection_name: null\n"
        "multitenant: false\n",
        encoding="utf-8",
    )

    for _ in range(2):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="secrets",
            adapter="env",
            adapter_params={
                "field_path": "adapters.mongodb.uri",
                "secret_key": "MONGODB_URI",
            },
            yes=True,
        )
    secrets = yaml.safe_load((project_dir / "config" / "secrets.yaml").read_text(encoding="utf-8"))

    assert secrets["resolver"] == "env"
    assert secrets["mappings"] == {
        "adapters.lm.api_key": "OPENAI_API_KEY",
        "adapters.mongodb.uri": "MONGODB_URI",
    }

    monkeypatch.setenv("MONGODB_URI", "mongodb://env:27017")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from arclith import Arclith

    arclith = Arclith(project_dir / "config")

    assert arclith.config.adapters.mongodb is not None
    assert arclith.config.adapters.mongodb.uri == "mongodb://env:27017"


def test_add_env_secrets_adapter_allows_derived_env_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _minimal_project(tmp_path)
    outbound_dir = project_dir / "config" / "adapters" / "outbound"
    outbound_dir.mkdir(parents=True, exist_ok=True)
    (outbound_dir / "mongodb.yaml").write_text(
        "uri: null\n"
        "db_name: demo\n"
        "collection_name: null\n"
        "multitenant: false\n",
        encoding="utf-8",
    )

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="secrets",
        adapter="env",
        adapter_params={"field_path": "adapters.mongodb.uri"},
        yes=True,
    )
    secrets = yaml.safe_load((project_dir / "config" / "secrets.yaml").read_text(encoding="utf-8"))

    assert secrets["resolver"] == "env"
    assert secrets["mappings"]["adapters.mongodb.uri"] == ""

    monkeypatch.setenv("ADAPTERS_MONGODB_URI", "mongodb://derived:27017")
    from arclith import Arclith

    arclith = Arclith(project_dir / "config")

    assert arclith.config.adapters.mongodb is not None
    assert arclith.config.adapters.mongodb.uri == "mongodb://derived:27017"


def test_add_env_secrets_adapter_requires_field_path(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    with pytest.raises(typer.Exit):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="secrets",
            adapter="env",
            yes=True,
        )

    assert not (project_dir / "config" / "secrets.yaml").exists()


def test_add_yaml_secrets_adapter_generates_template_and_preserves_real_secret_file(
    tmp_path: Path,
) -> None:
    project_dir = _minimal_project(tmp_path)
    outbound_dir = project_dir / "config" / "adapters" / "outbound"
    outbound_dir.mkdir(parents=True, exist_ok=True)
    (outbound_dir / "mongodb.yaml").write_text(
        "uri: null\n"
        "db_name: demo\n"
        "collection_name: null\n"
        "multitenant: false\n",
        encoding="utf-8",
    )
    real_secret = "adapters:\n  mongodb:\n    uri: mongodb://local:27017\n"
    (project_dir / "secrets.yaml").write_text(real_secret, encoding="utf-8")

    for _ in range(2):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="secrets",
            adapter="yaml",
            adapter_params={
                "field_path": "adapters.mongodb.uri",
                "path": "secrets.yaml",
            },
            yes=True,
        )
    config_secrets = yaml.safe_load((project_dir / "config" / "secrets.yaml").read_text(encoding="utf-8"))
    template = (project_dir / "secrets.yaml.template").read_text(encoding="utf-8")
    gitignore = (project_dir / ".gitignore").read_text(encoding="utf-8")

    assert config_secrets["resolver"] == "yaml"
    assert config_secrets["yaml"] == {"path": "secrets.yaml"}
    assert config_secrets["mappings"]["adapters.mongodb.uri"] == ""
    assert (project_dir / "secrets.yaml").read_text(encoding="utf-8") == real_secret
    assert "secrets.yaml" in gitignore.splitlines()
    assert "mongodb://local:27017" not in template
    assert yaml.safe_load("\n".join(template.splitlines()[2:])) == {
        "adapters": {"mongodb": {"uri": "replace-me"}}
    }

    subprocess.run(["git", "init"], cwd=project_dir, check=True, capture_output=True, text=True)
    ignored = subprocess.run(
        ["git", "check-ignore", "secrets.yaml"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert ignored.returncode == 0

    from arclith import Arclith

    arclith = Arclith(project_dir / "config")

    assert arclith.config.adapters.mongodb is not None
    assert arclith.config.adapters.mongodb.uri == "mongodb://local:27017"


def test_add_vault_secrets_adapter_generates_safe_config_and_resolves_with_fake_hvac(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = _minimal_project(tmp_path)
    outbound_dir = project_dir / "config" / "adapters" / "outbound"
    outbound_dir.mkdir(parents=True, exist_ok=True)
    (outbound_dir / "mongodb.yaml").write_text(
        "uri: null\n"
        "db_name: demo\n"
        "collection_name: null\n"
        "multitenant: false\n",
        encoding="utf-8",
    )

    for _ in range(2):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="secrets",
            adapter="vault",
            adapter_params={
                "field_path": "adapters.mongodb.uri",
                "secret_key": "apps/demo/mongodb",
                "addr": "http://vault:8200",
                "mount": "kv-app",
            },
            yes=True,
        )
    secrets_text = (project_dir / "config" / "secrets.yaml").read_text(encoding="utf-8")
    secrets = yaml.safe_load(secrets_text)

    assert secrets["resolver"] == "vault"
    assert secrets["vault"] == {"addr": "http://vault:8200", "mount": "kv-app"}
    assert secrets["mappings"] == {"adapters.mongodb.uri": "apps/demo/mongodb"}
    assert "VAULT_TOKEN" not in secrets_text
    assert "mongodb://vault:27017" not in secrets_text

    fake_client = MagicMock()
    fake_client.is_authenticated.return_value = True
    fake_client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"value": "mongodb://vault:27017"}}
    }
    fake_hvac = MagicMock()
    fake_hvac.Client.return_value = fake_client
    monkeypatch.setitem(sys.modules, "hvac", fake_hvac)
    monkeypatch.setenv("VAULT_TOKEN", "test-token")

    from arclith import Arclith

    arclith = Arclith(project_dir / "config")

    assert arclith.config.adapters.mongodb is not None
    assert arclith.config.adapters.mongodb.uri == "mongodb://vault:27017"
    fake_hvac.Client.assert_called_with(url="http://vault:8200", token="test-token")
    fake_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
        path="apps/demo/mongodb",
        mount_point="kv-app",
        raise_on_deleted_version=True,
    )


def test_add_vault_secrets_adapter_requires_secret_key(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    with pytest.raises(typer.Exit):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="secrets",
            adapter="vault",
            adapter_params={"field_path": "adapters.mongodb.uri"},
            yes=True,
        )

    assert not (project_dir / "config" / "secrets.yaml").exists()


def test_add_chain_secrets_adapter_preserves_mappings_and_renders_ordered_fallback(
    tmp_path: Path,
) -> None:
    project_dir = _minimal_project(tmp_path)
    (project_dir / "config" / "secrets.yaml").write_text(
        "resolver: env\n"
        "mappings:\n"
        "  adapters.lm.api_key: OPENAI_API_KEY\n",
        encoding="utf-8",
    )

    for _ in range(2):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="secrets",
            adapter="chain",
            adapter_params={
                "field_path": "adapters.mongodb.uri",
                "secret_key": "apps/demo/mongodb",
                "resolvers": "env,vault,yaml",
                "addr": "http://vault:8200",
                "mount": "kv-app",
                "path": "secrets.yaml",
            },
            yes=True,
        )
    secrets = yaml.safe_load((project_dir / "config" / "secrets.yaml").read_text(encoding="utf-8"))

    assert secrets["resolver"] == "chain"
    assert secrets["chain"] == ["env", "vault", "yaml"]
    assert secrets["vault"] == {"addr": "http://vault:8200", "mount": "kv-app"}
    assert secrets["yaml"] == {"path": "secrets.yaml"}
    assert secrets["mappings"] == {
        "adapters.lm.api_key": "OPENAI_API_KEY",
        "adapters.mongodb.uri": "apps/demo/mongodb",
    }


def test_add_chain_secrets_adapter_rejects_unknown_resolver(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)

    with pytest.raises(typer.Exit):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="secrets",
            adapter="chain",
            adapter_params={
                "field_path": "adapters.mongodb.uri",
                "secret_key": "apps/demo/mongodb",
                "resolvers": "env,unknown",
            },
            yes=True,
        )

    assert not (project_dir / "config" / "secrets.yaml").exists()


def test_boolean_string_default_false_is_false(tmp_path: Path) -> None:
    parameter = ParameterSpec(name="multitenant", kind="boolean", prompt="multitenant", default="false")

    assert _resolve_parameter(parameter, None, tmp_path, prompt_missing=False) is False


def test_non_interactive_requires_entity_when_multiple_models(tmp_path: Path) -> None:
    project_dir = _minimal_project(tmp_path)
    _write_model(project_dir, "demo_service", "Recipe", "recipe")

    with pytest.raises(typer.Exit):
        add_adapter_cmd(project_dir=project_dir, adapter="memory", yes=True)
