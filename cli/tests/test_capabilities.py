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
    memory = capability.get_adapter("memory")
    assert memory is not None
    assert memory.entity_scoped is True
    assert memory.config_path is None
    assert memory.parameters == ()


def test_observability_capability_catalog_declares_langsmith() -> None:
    capability = get_capability("observability")

    assert capability is not None
    assert capability.layer == "outbound"
    assert capability.activation_config_key == "observability"
    assert capability.adapter_names() == ("langsmith", "opentelemetry")
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


def test_api_capability_catalog_declares_fastapi() -> None:
    capability = get_capability("api")

    assert capability is not None
    assert capability.layer == "inbound"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("fastapi",)
    fastapi = capability.get_adapter("fastapi")
    assert fastapi is not None
    assert fastapi.config_path == "config/adapters/inbound/fastapi.yaml"
    assert fastapi.entity_scoped is False
    assert [parameter.name for parameter in fastapi.parameters] == ["host", "port", "reload"]


def test_mcp_capability_catalog_declares_fastmcp() -> None:
    capability = get_capability("mcp")

    assert capability is not None
    assert capability.layer == "inbound"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("fastmcp",)
    fastmcp = capability.get_adapter("fastmcp")
    assert fastmcp is not None
    assert fastmcp.config_path == "config/adapters/inbound/fastmcp.yaml"
    assert fastmcp.entity_scoped is False
    assert [parameter.name for parameter in fastmcp.parameters] == ["host", "port"]


def test_llm_capability_catalog_declares_model_adapters() -> None:
    capability = get_capability("llm")

    assert capability is not None
    assert capability.layer == "outbound"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("lmstudio", "openai", "anthropic")

    lmstudio = capability.get_adapter("lmstudio")
    openai = capability.get_adapter("openai")
    anthropic = capability.get_adapter("anthropic")

    assert lmstudio is not None
    assert lmstudio.config_path == "config/adapters/outbound/lm.yaml"
    assert lmstudio.entity_scoped is False
    assert [parameter.name for parameter in lmstudio.parameters] == ["model_name", "base_url", "api_key"]

    assert openai is not None
    assert openai.config_path == "config/adapters/outbound/lm.yaml"
    assert openai.env_path == ".env"
    assert openai.entity_scoped is False
    openai_parameters = {parameter.name: parameter for parameter in openai.parameters}
    assert openai_parameters["model_name"].default == "remplacer-par-model-id-openai"
    assert openai_parameters["api_key"].secret is True
    assert openai_parameters["api_key"].default == ""
    assert [mapping.field_path for mapping in openai.secret_mappings] == ["adapters.lm.api_key"]

    assert anthropic is not None
    assert anthropic.config_path == "config/adapters/outbound/lm.yaml"
    assert anthropic.env_path == ".env"
    assert anthropic.entity_scoped is False
    assert [mapping.secret_key for mapping in anthropic.secret_mappings] == ["ANTHROPIC_API_KEY"]


def test_observability_capability_catalog_declares_opentelemetry() -> None:
    capability = get_capability("observability")

    assert capability is not None
    opentelemetry = capability.get_adapter("opentelemetry")
    assert opentelemetry is not None
    assert opentelemetry.config_path == "config/adapters/outbound/opentelemetry.yaml"
    assert opentelemetry.env_path == ".env"
    assert opentelemetry.entity_scoped is False
    assert [parameter.name for parameter in opentelemetry.parameters] == [
        "service_name",
        "endpoint",
        "traces_endpoint",
        "metrics_endpoint",
        "protocol",
        "traces",
        "metrics",
        "instrument_fastapi",
        "metrics_export_interval_millis",
        "headers",
    ]


def test_agent_capability_catalog_declares_langgraph() -> None:
    capability = get_capability("agent")

    assert capability is not None
    assert capability.layer == "inbound"
    assert capability.activation_config_key is None
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
    assert [parameter.name for parameter in mongodb.parameters] == ["db_name", "collection_name", "multitenant"]
    assert [mapping.field_path for mapping in mongodb.secret_mappings] == ["adapters.mongodb.uri"]
    assert [mapping.secret_key for mapping in mongodb.secret_mappings] == ["MONGODB_URI"]
    assert duckdb is not None
    assert duckdb.config_path == "config/adapters/outbound/duckdb.yaml"
    assert [parameter.name for parameter in duckdb.parameters] == ["path"]
    assert mariadb is not None
    assert mariadb.config_path == "config/adapters/outbound/mariadb.yaml"
    assert [mapping.field_path for mapping in mariadb.secret_mappings] == [
        "adapters.mariadb.url",
        "adapters.mariadb.password",
    ]
    assert [mapping.secret_key for mapping in mariadb.secret_mappings] == [
        "MARIADB_URL",
        "MARIADB_PASSWORD",
    ]
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
    assert "api" in encoded
    assert "fastapi" in encoded
    assert "mcp" in encoded
    assert "fastmcp" in encoded
    assert "llm" in encoded
    assert "lmstudio" in encoded
    assert "agent" in encoded
    assert "langgraph" in encoded
    assert "observability" in encoded
    assert "langsmith" in encoded
    assert "opentelemetry" in encoded


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
    assert payload[0]["adapters"][0]["entity_scoped"] is True
    duckdb = payload[0]["adapters"][2]
    assert duckdb["name"] == "duckdb"
    assert duckdb["config_path"] == "config/adapters/outbound/duckdb.yaml"
    assert [parameter["name"] for parameter in duckdb["parameters"]] == ["path"]
    mariadb = payload[0]["adapters"][3]
    assert mariadb["name"] == "mariadb"
    assert [mapping["field_path"] for mapping in mariadb["secret_mappings"]] == [
        "adapters.mariadb.url",
        "adapters.mariadb.password",
    ]
    assert [mapping["secret_key"] for mapping in mariadb["secret_mappings"]] == [
        "MARIADB_URL",
        "MARIADB_PASSWORD",
    ]
    assert payload[1]["name"] == "api"
    assert [adapter["name"] for adapter in payload[1]["adapters"]] == ["fastapi"]
    assert payload[2]["name"] == "mcp"
    assert [adapter["name"] for adapter in payload[2]["adapters"]] == ["fastmcp"]
    assert payload[3]["name"] == "llm"
    assert [adapter["name"] for adapter in payload[3]["adapters"]] == ["lmstudio", "openai", "anthropic"]
    openai = payload[3]["adapters"][1]
    openai_parameters = {parameter["name"]: parameter for parameter in openai["parameters"]}
    assert openai_parameters["model_name"]["default"] == "remplacer-par-model-id-openai"
    assert openai_parameters["api_key"]["secret"] is True
    assert openai_parameters["api_key"]["default"] == ""
    assert payload[4]["name"] == "agent"
    assert [adapter["name"] for adapter in payload[4]["adapters"]] == ["langgraph"]
    assert payload[5]["name"] == "observability"
    assert [adapter["name"] for adapter in payload[5]["adapters"]] == ["langsmith", "opentelemetry"]
