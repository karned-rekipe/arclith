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


def test_cache_capability_catalog_declares_memory_adapter() -> None:
    capability = get_capability("cache")

    assert capability is not None
    assert capability.layer == "outbound"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("memory", "redis")
    memory = capability.get_adapter("memory")
    redis = capability.get_adapter("redis")
    assert memory is not None
    assert memory.capability == "cache"
    assert memory.config_path == "config/adapters/inbound/cache.yaml"
    assert memory.entity_scoped is False
    assert [parameter.name for parameter in memory.parameters] == ["jwks_ttl", "tenant_uri_ttl"]
    assert redis is not None
    assert redis.capability == "cache"
    assert redis.config_path == "config/adapters/inbound/cache.yaml"
    assert redis.env_path == ".env"
    assert redis.entity_scoped is False
    assert [parameter.name for parameter in redis.parameters] == ["redis_url", "jwks_ttl", "tenant_uri_ttl"]
    assert [mapping.field_path for mapping in redis.secret_mappings] == ["cache.redis_url"]
    assert [mapping.secret_key for mapping in redis.secret_mappings] == ["REDIS_URL"]


def test_secrets_capability_catalog_declares_env_adapter() -> None:
    capability = get_capability("secrets")

    assert capability is not None
    assert capability.layer == "outbound"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("env",)
    env = capability.get_adapter("env")
    assert env is not None
    assert env.config_path is None
    assert env.secret_resolver == "env"
    assert env.entity_scoped is False
    assert [parameter.name for parameter in env.parameters] == ["field_path", "secret_key"]
    assert env.parameters[0].required is True
    assert [mapping.field_path for mapping in env.secret_mappings] == ["{field_path}"]
    assert [mapping.secret_key for mapping in env.secret_mappings] == ["{secret_key}"]


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
    langsmith_parameters = {parameter.name: parameter for parameter in langsmith.parameters}
    assert langsmith_parameters["api_key"].secret is True
    assert langsmith_parameters["api_key"].default == ""


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


def test_auth_capability_catalog_declares_keycloak() -> None:
    capability = get_capability("auth")

    assert capability is not None
    assert capability.layer == "inbound"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("keycloak",)
    keycloak = capability.get_adapter("keycloak")
    assert keycloak is not None
    assert keycloak.config_path == "config/adapters/inbound/keycloak.yaml"
    assert keycloak.entity_scoped is False
    assert [parameter.name for parameter in keycloak.parameters] == ["url", "realm", "audience", "client_id"]


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
    anthropic_parameters = {parameter.name: parameter for parameter in anthropic.parameters}
    assert anthropic_parameters["model_name"].default == "remplacer-par-model-id-anthropic"
    assert anthropic_parameters["api_key"].secret is True
    assert anthropic_parameters["api_key"].default == ""
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
    assert "cache" in encoded
    assert "redis" in encoded
    assert "secrets" in encoded
    assert "env" in encoded
    assert "api" in encoded
    assert "fastapi" in encoded
    assert "mcp" in encoded
    assert "fastmcp" in encoded
    assert "auth" in encoded
    assert "keycloak" in encoded
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
    payload_by_name = {capability["name"]: capability for capability in payload}
    repository = payload_by_name["repository"]
    assert [adapter["name"] for adapter in repository["adapters"]] == ["memory", "mongodb", "duckdb", "mariadb"]
    assert repository["adapters"][0]["entity_scoped"] is True
    duckdb = repository["adapters"][2]
    assert duckdb["name"] == "duckdb"
    assert duckdb["config_path"] == "config/adapters/outbound/duckdb.yaml"
    assert [parameter["name"] for parameter in duckdb["parameters"]] == ["path"]
    mariadb = repository["adapters"][3]
    assert mariadb["name"] == "mariadb"
    assert [mapping["field_path"] for mapping in mariadb["secret_mappings"]] == [
        "adapters.mariadb.url",
        "adapters.mariadb.password",
    ]
    assert [mapping["secret_key"] for mapping in mariadb["secret_mappings"]] == [
        "MARIADB_URL",
        "MARIADB_PASSWORD",
    ]
    cache = payload_by_name["cache"]
    assert [adapter["name"] for adapter in cache["adapters"]] == ["memory", "redis"]
    assert cache["adapters"][0]["capability"] == "cache"
    assert cache["adapters"][0]["entity_scoped"] is False
    assert [parameter["name"] for parameter in cache["adapters"][0]["parameters"]] == [
        "jwks_ttl",
        "tenant_uri_ttl",
    ]
    assert cache["adapters"][1]["capability"] == "cache"
    assert cache["adapters"][1]["entity_scoped"] is False
    assert [parameter["name"] for parameter in cache["adapters"][1]["parameters"]] == [
        "redis_url",
        "jwks_ttl",
        "tenant_uri_ttl",
    ]
    assert [mapping["field_path"] for mapping in cache["adapters"][1]["secret_mappings"]] == [
        "cache.redis_url"
    ]
    secrets = payload_by_name["secrets"]
    assert [adapter["name"] for adapter in secrets["adapters"]] == ["env"]
    env = secrets["adapters"][0]
    assert env["secret_resolver"] == "env"
    assert [parameter["name"] for parameter in env["parameters"]] == ["field_path", "secret_key"]
    assert env["parameters"][0]["required"] is True
    assert [adapter["name"] for adapter in payload_by_name["api"]["adapters"]] == ["fastapi"]
    assert [adapter["name"] for adapter in payload_by_name["mcp"]["adapters"]] == ["fastmcp"]
    auth = payload_by_name["auth"]
    assert [adapter["name"] for adapter in auth["adapters"]] == ["keycloak"]
    keycloak_parameters = {parameter["name"]: parameter for parameter in auth["adapters"][0]["parameters"]}
    assert keycloak_parameters["url"]["default"] == "http://localhost:8080"
    assert keycloak_parameters["realm"]["default"] == "rekipe"
    assert keycloak_parameters["audience"]["default"] == "null"
    assert keycloak_parameters["client_id"]["default"] == "null"
    llm = payload_by_name["llm"]
    assert [adapter["name"] for adapter in llm["adapters"]] == ["lmstudio", "openai", "anthropic"]
    openai = llm["adapters"][1]
    openai_parameters = {parameter["name"]: parameter for parameter in openai["parameters"]}
    assert openai_parameters["model_name"]["default"] == "remplacer-par-model-id-openai"
    assert openai_parameters["api_key"]["secret"] is True
    assert openai_parameters["api_key"]["default"] == ""
    anthropic = llm["adapters"][2]
    anthropic_parameters = {parameter["name"]: parameter for parameter in anthropic["parameters"]}
    assert anthropic_parameters["model_name"]["default"] == "remplacer-par-model-id-anthropic"
    assert anthropic_parameters["api_key"]["secret"] is True
    assert anthropic_parameters["api_key"]["default"] == ""
    assert [adapter["name"] for adapter in payload_by_name["agent"]["adapters"]] == ["langgraph"]
    observability = payload_by_name["observability"]
    assert [adapter["name"] for adapter in observability["adapters"]] == ["langsmith", "opentelemetry"]
    langsmith = observability["adapters"][0]
    langsmith_parameters = {parameter["name"]: parameter for parameter in langsmith["parameters"]}
    assert langsmith_parameters["api_key"]["secret"] is True
    assert langsmith_parameters["api_key"]["default"] == ""
