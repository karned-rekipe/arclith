import json
import subprocess

from arclith_cli.capabilities import (
    capability_catalog_as_dict,
    get_capability,
    repository_adapter_names,
)


def test_repository_capability_catalog_declares_standard_adapters() -> None:
    capability = get_capability("repository")

    assert capability is not None
    assert capability.layer == "outbound"
    assert capability.activation_config_key == "repository"
    assert repository_adapter_names() == ("memory", "mongodb", "duckdb", "mariadb")


def test_observability_capability_catalog_declares_langsmith() -> None:
    capability = get_capability("observability")

    assert capability is not None
    assert capability.layer == "outbound"
    assert capability.activation_config_key == "observability"
    assert capability.adapter_names() == ("langsmith",)
    langsmith = capability.get_adapter("langsmith")
    assert langsmith is not None
    assert langsmith.config_path == "config/adapters/outbound/langsmith.yaml"
    assert langsmith.env_path == ".env"
    assert langsmith.entity_scoped is False
    assert [parameter.name for parameter in langsmith.parameters] == [
        "tracing",
        "project",
        "endpoint",
        "api_key",
    ]


def test_agent_capability_catalog_declares_langgraph() -> None:
    capability = get_capability("agent")

    assert capability is not None
    assert capability.layer == "inbound"
    assert capability.activation_config_key == "agent"
    assert capability.adapter_names() == ("langgraph",)
    langgraph = capability.get_adapter("langgraph")
    assert langgraph is not None
    assert langgraph.config_path == "config/adapters/inbound/langgraph.yaml"
    assert langgraph.entity_scoped is False
    assert [file_template.path for file_template in langgraph.file_templates] == [
        "langgraph.json",
        "{package_path}/adapters/inbound/langgraph/__init__.py",
        "{package_path}/adapters/inbound/langgraph/agent.py",
    ]
    assert [parameter.name for parameter in langgraph.parameters] == ["graph_name"]


def test_repository_adapter_specs_include_config_and_parameters() -> None:
    capability = get_capability("repository")
    assert capability is not None

    mongodb = capability.get_adapter("mongodb")
    duckdb = capability.get_adapter("duckdb")
    mariadb = capability.get_adapter("mariadb")

    assert mongodb is not None
    assert mongodb.config_path == "config/adapters/outbound/mongodb.yaml"
    assert [parameter.name for parameter in mongodb.parameters] == ["db_name", "multitenant"]
    assert duckdb is not None
    assert duckdb.config_path == "config/adapters/outbound/duckdb.yaml"
    assert [parameter.name for parameter in duckdb.parameters] == ["path"]
    assert mariadb is not None
    assert mariadb.config_path == "config/adapters/outbound/mariadb.yaml"
    assert [parameter.name for parameter in mariadb.parameters] == [
        "host",
        "port",
        "database",
        "user",
        "driver",
        "table_prefix",
    ]


def test_capability_catalog_is_json_serializable() -> None:
    payload = capability_catalog_as_dict()

    encoded = json.dumps(payload)

    assert "repository" in encoded
    assert "mongodb" in encoded
    assert "agent" in encoded
    assert "langgraph" in encoded
    assert "observability" in encoded
    assert "langsmith" in encoded


def test_capabilities_command_outputs_json_catalog() -> None:
    result = subprocess.run(
        ["arclith-cli", "capabilities", "--json"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload[0]["name"] == "repository"
    assert [adapter["name"] for adapter in payload[0]["adapters"]] == ["memory", "mongodb", "duckdb", "mariadb"]
    assert payload[1]["name"] == "agent"
    assert [adapter["name"] for adapter in payload[1]["adapters"]] == ["langgraph"]
    assert payload[2]["name"] == "observability"
    assert [adapter["name"] for adapter in payload[2]["adapters"]] == ["langsmith"]
