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
