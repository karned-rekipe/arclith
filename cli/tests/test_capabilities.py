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
    assert repository_adapter_names() == (
        "memory",
        "mongodb",
        "duckdb",
        "mariadb",
        "postgresql",
    )
    memory = capability.get_adapter("memory")
    assert memory is not None
    assert memory.entity_scoped is True
    assert memory.config_path is None
    assert memory.parameters == ()
    postgresql = capability.get_adapter("postgresql")
    assert postgresql is not None
    assert postgresql.config_path == "config/adapters/outbound/postgresql.yaml"
    assert [mapping.field_path for mapping in postgresql.secret_mappings] == [
        "adapters.postgresql.url",
        "adapters.postgresql.password",
    ]
    assert [mapping.secret_key for mapping in postgresql.secret_mappings] == [
        "POSTGRESQL_URL",
        "POSTGRESQL_PASSWORD",
    ]
    assert [parameter.name for parameter in postgresql.parameters] == [
        "host",
        "port",
        "database",
        "user",
        "schema",
        "driver",
        "table_prefix",
        "multitenant",
    ]


def test_repository_adapter_facets_have_a_stable_serializable_shape() -> None:
    capability = get_capability("repository")
    assert capability is not None

    expected_facets = {
        "memory": (
            "memory",
            "in_process",
            False,
            False,
            "none",
            "flexible",
        ),
        "mongodb": (
            "document",
            "server",
            True,
            True,
            "limited",
            "flexible",
        ),
        "duckdb": (
            "embedded_analytics",
            "file",
            False,
            False,
            "limited",
            "structured_tables",
        ),
        "mariadb": (
            "relational_json",
            "server",
            True,
            True,
            "strong",
            "json_table",
        ),
        "postgresql": (
            "relational_json",
            "server",
            True,
            True,
            "strong",
            "json_table",
        ),
    }

    for adapter in capability.adapters:
        assert adapter.facets is not None
        payload = adapter.facets.to_dict()
        assert set(payload) == {
            "storage_model",
            "runtime",
            "production_ready",
            "multi_process",
            "transactions",
            "schema_strategy",
            "recommended_for",
            "limits",
        }
        assert (
            payload["storage_model"],
            payload["runtime"],
            payload["production_ready"],
            payload["multi_process"],
            payload["transactions"],
            payload["schema_strategy"],
        ) == expected_facets[adapter.name]
        assert payload["recommended_for"]
        assert all(isinstance(value, str) for value in payload["recommended_for"])
        assert payload["limits"]
        assert all(isinstance(value, str) for value in payload["limits"])


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
    assert [parameter.name for parameter in memory.parameters] == [
        "jwks_ttl",
        "tenant_uri_ttl",
    ]
    assert redis is not None
    assert redis.capability == "cache"
    assert redis.config_path == "config/adapters/inbound/cache.yaml"
    assert redis.env_path == ".env"
    assert redis.entity_scoped is False
    assert [parameter.name for parameter in redis.parameters] == [
        "redis_url",
        "jwks_ttl",
        "tenant_uri_ttl",
    ]
    assert [mapping.field_path for mapping in redis.secret_mappings] == [
        "cache.redis_url"
    ]
    assert [mapping.secret_key for mapping in redis.secret_mappings] == ["REDIS_URL"]


def test_logger_capability_catalog_declares_console_adapter() -> None:
    capability = get_capability("logger")

    assert capability is not None
    assert capability.layer == "outbound"
    assert capability.activation_config_key == "logger"
    assert capability.adapter_names() == ("console",)
    console = capability.get_adapter("console")
    assert console is not None
    assert console.config_path is None
    assert console.entity_scoped is False
    assert console.parameters == ()


def test_secrets_capability_catalog_declares_env_adapter() -> None:
    capability = get_capability("secrets")

    assert capability is not None
    assert capability.layer == "outbound"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("env", "yaml", "vault", "chain")
    env = capability.get_adapter("env")
    yaml = capability.get_adapter("yaml")
    vault = capability.get_adapter("vault")
    chain = capability.get_adapter("chain")
    assert env is not None
    assert env.config_path is None
    assert env.secret_resolver == "env"
    assert env.entity_scoped is False
    assert [parameter.name for parameter in env.parameters] == [
        "field_path",
        "secret_key",
    ]
    assert env.parameters[0].required is True
    assert [mapping.field_path for mapping in env.secret_mappings] == ["{field_path}"]
    assert [mapping.secret_key for mapping in env.secret_mappings] == ["{secret_key}"]
    assert yaml is not None
    assert yaml.config_path is None
    assert yaml.secret_resolver == "yaml"
    assert yaml.gitignore_entries == ("secrets.yaml",)
    assert [file_template.path for file_template in yaml.file_templates] == [
        "secrets.yaml.template"
    ]
    assert [parameter.name for parameter in yaml.parameters] == [
        "field_path",
        "secret_key",
        "path",
    ]
    assert vault is not None
    assert vault.config_path is None
    assert vault.secret_resolver == "vault"
    assert vault.entity_scoped is False
    assert [parameter.name for parameter in vault.parameters] == [
        "field_path",
        "secret_key",
        "addr",
        "mount",
    ]
    assert vault.parameters[0].required is True
    assert vault.parameters[1].required is True
    assert chain is not None
    assert chain.config_path is None
    assert chain.secret_resolver == "chain"
    assert chain.entity_scoped is False
    assert [parameter.name for parameter in chain.parameters] == [
        "field_path",
        "secret_key",
        "resolvers",
        "addr",
        "mount",
        "path",
    ]
    assert chain.parameters[2].choices == ("env", "vault", "yaml")
    assert chain.parameters[2].csv_choices is True


def test_observability_capability_catalog_declares_langsmith() -> None:
    capability = get_capability("observability")

    assert capability is not None
    assert capability.layer == "outbound"
    assert capability.activation_config_key == "observability"
    assert capability.adapter_names() == ("langsmith", "opentelemetry")
    langsmith = capability.get_adapter("langsmith")
    assert langsmith is not None
    assert langsmith.config_path == "config/adapters/outbound/langsmith.yaml"
    assert langsmith.env_path == ".env.example"
    assert langsmith.dependency_extra == "langsmith"
    assert langsmith.entity_scoped is False
    assert [parameter.name for parameter in langsmith.parameters] == [
        "tracing_enabled",
        "project",
        "endpoint",
        "tracing_mode",
        "sampling_rate",
        "capture_inputs",
        "capture_outputs",
        "capture_metadata",
        "capture_model_content",
        "instrument_langgraph",
        "instrument_pydantic_ai",
        "instrument_fastapi",
        "instrument_fastmcp",
        "instrument_command_bus",
        "diagnostics_enabled",
    ]
    assert [profile.name for profile in langsmith.profiles] == [
        "development",
        "production",
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
    assert [parameter.name for parameter in fastapi.parameters] == [
        "host",
        "port",
        "reload",
    ]


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


def test_probe_capability_catalog_declares_server() -> None:
    capability = get_capability("probe")

    assert capability is not None
    assert capability.layer == "inbound"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("server",)
    server = capability.get_adapter("server")
    assert server is not None
    assert server.config_path == "config/adapters/inbound/probe.yaml"
    assert server.entity_scoped is False
    assert [parameter.name for parameter in server.parameters] == [
        "host",
        "port",
        "enabled",
    ]


def test_http_capability_catalog_declares_idempotency() -> None:
    capability = get_capability("http")

    assert capability is not None
    assert capability.layer == "inbound"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("idempotency", "etag", "cache-control")
    idempotency = capability.get_adapter("idempotency")
    etag = capability.get_adapter("etag")
    cache_control = capability.get_adapter("cache-control")
    assert idempotency is not None
    assert idempotency.config_path is None
    assert [template.path for template in idempotency.merge_config_templates] == [
        "config/http.yaml"
    ]
    assert idempotency.entity_scoped is False
    assert [parameter.name for parameter in idempotency.parameters] == [
        "enabled",
        "ttl_seconds",
        "required",
    ]
    assert etag is not None
    assert etag.config_path is None
    assert [template.path for template in etag.merge_config_templates] == [
        "config/http.yaml"
    ]
    assert etag.entity_scoped is False
    assert [parameter.name for parameter in etag.parameters] == ["enabled"]
    assert cache_control is not None
    assert cache_control.config_path is None
    assert [template.path for template in cache_control.merge_config_templates] == [
        "config/http.yaml"
    ]
    assert cache_control.entity_scoped is False
    assert [parameter.name for parameter in cache_control.parameters] == [
        "get_single_max_age",
        "get_list_max_age",
    ]


def test_command_bus_capability_catalog_declares_rabbitmq() -> None:
    capability = get_capability("command-bus")

    assert capability is not None
    assert capability.layer == "bidirectional"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("rabbitmq",)
    rabbitmq = capability.get_adapter("rabbitmq")
    assert rabbitmq is not None
    assert rabbitmq.layer == "bidirectional"
    assert rabbitmq.config_path is None
    assert [template.path for template in rabbitmq.merge_config_templates] == [
        "config/command_bus.yaml"
    ]
    assert rabbitmq.entity_scoped is False
    assert [parameter.name for parameter in rabbitmq.parameters] == [
        "url",
        "exchange",
        "exchange_type",
        "queue",
        "routing_key",
        "prefetch",
        "consumer_name",
        "concurrency",
        "publisher_confirms",
        "durable",
        "retry_enabled",
        "retry_requeue",
        "dead_letter_exchange",
        "dead_letter_routing_key",
    ]


def test_channel_capability_catalog_declares_memory_and_webhook_adapters() -> None:
    capability = get_capability("channel")

    assert capability is not None
    assert capability.layer == "bidirectional"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("memory", "webhook")
    memory = capability.get_adapter("memory")
    assert memory is not None
    assert memory.layer == "bidirectional"
    assert memory.config_path == "config/adapters/bidirectional/memory.yaml"
    assert memory.dependency_extra is None
    assert memory.entity_scoped is False
    assert memory.parameters == ()
    webhook = capability.get_adapter("webhook")
    assert webhook is not None
    assert webhook.layer == "bidirectional"
    assert webhook.config_path == "config/adapters/bidirectional/webhook.yaml"
    assert webhook.dependency_extra == "channel"
    assert webhook.entity_scoped is False
    assert [parameter.name for parameter in webhook.parameters] == [
        "path",
        "signature_header",
        "timestamp_header",
        "signature_tolerance_seconds",
        "idempotency_header",
        "event_ttl_seconds",
        "max_payload_bytes",
        "response_mode",
        "callback_url",
        "callback_allowed_host",
        "callback_timeout_seconds",
    ]
    assert [mapping.field_path for mapping in webhook.secret_mappings] == [
        "adapters.channel.webhook.secret"
    ]
    assert [mapping.secret_key for mapping in webhook.secret_mappings] == [
        "ARCLITH_WEBHOOK_SECRET"
    ]


def test_runtime_capability_catalog_declares_docker_image() -> None:
    capability = get_capability("runtime")

    assert capability is not None
    assert capability.layer == "runtime"
    assert (
        capability.description
        == "Runtime de déploiement standardisé pour images et processus Arclith."
    )
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("docker-image",)
    docker_image = capability.get_adapter("docker-image")
    assert docker_image is not None
    assert docker_image.layer == "runtime"
    assert docker_image.config_path is None
    assert [template.path for template in docker_image.file_templates] == [
        "Dockerfile",
        ".dockerignore",
        "arclith-run",
    ]
    assert docker_image.entity_scoped is False
    assert [parameter.name for parameter in docker_image.parameters] == [
        "uv_version",
        "api_port",
        "mcp_port",
        "probe_port",
        "agent_port",
    ]


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
    assert [parameter.name for parameter in keycloak.parameters] == [
        "url",
        "realm",
        "audience",
        "client_id",
    ]


def test_tenant_capability_catalog_declares_vault() -> None:
    capability = get_capability("tenant")

    assert capability is not None
    assert capability.layer == "inbound"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("vault",)
    vault = capability.get_adapter("vault")
    assert vault is not None
    assert vault.config_path == "config/adapters/inbound/tenant.yaml"
    assert [template.path for template in vault.merge_config_templates] == [
        "config/adapters/inbound/cache.yaml"
    ]
    assert vault.entity_scoped is False
    assert [parameter.name for parameter in vault.parameters] == [
        "addr",
        "mount",
        "path_prefix",
        "tenant_claim",
        "tenant_uri_ttl",
    ]


def test_license_capability_catalog_declares_role() -> None:
    capability = get_capability("license")

    assert capability is not None
    assert capability.layer == "inbound"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("role",)
    role = capability.get_adapter("role")
    assert role is not None
    assert role.config_path == "config/adapters/inbound/license.yaml"
    assert role.entity_scoped is False
    assert [parameter.name for parameter in role.parameters] == ["role"]


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
    assert [parameter.name for parameter in lmstudio.parameters] == [
        "model_name",
        "base_url",
        "api_key",
    ]

    assert openai is not None
    assert openai.config_path == "config/adapters/outbound/lm.yaml"
    assert openai.env_path == ".env"
    assert openai.entity_scoped is False
    openai_parameters = {parameter.name: parameter for parameter in openai.parameters}
    assert openai_parameters["model_name"].default == "remplacer-par-model-id-openai"
    assert openai_parameters["api_key"].secret is True
    assert openai_parameters["api_key"].default == ""
    assert [mapping.field_path for mapping in openai.secret_mappings] == [
        "adapters.lm.api_key"
    ]

    assert anthropic is not None
    assert anthropic.config_path == "config/adapters/outbound/lm.yaml"
    assert anthropic.env_path == ".env"
    assert anthropic.entity_scoped is False
    anthropic_parameters = {
        parameter.name: parameter for parameter in anthropic.parameters
    }
    assert (
        anthropic_parameters["model_name"].default == "remplacer-par-model-id-anthropic"
    )
    assert anthropic_parameters["api_key"].secret is True
    assert anthropic_parameters["api_key"].default == ""
    assert [mapping.secret_key for mapping in anthropic.secret_mappings] == [
        "ANTHROPIC_API_KEY"
    ]


def test_observability_capability_catalog_declares_opentelemetry() -> None:
    capability = get_capability("observability")

    assert capability is not None
    opentelemetry = capability.get_adapter("opentelemetry")
    assert opentelemetry is not None
    assert opentelemetry.config_path == "config/adapters/outbound/opentelemetry.yaml"
    assert opentelemetry.env_path == ".env.example"
    assert opentelemetry.dependency_extra == "opentelemetry"
    assert opentelemetry.entity_scoped is False
    assert [parameter.name for parameter in opentelemetry.parameters] == [
        "service_name",
        "endpoint",
        "mode",
        "protocol",
        "traces",
        "metrics",
        "logs",
        "correlate_logs",
        "sampling_ratio",
        "metrics_export_interval_millis",
        "deployment_environment",
    ]
    assert [profile.name for profile in opentelemetry.profiles] == [
        "development",
        "production",
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
    assert [parameter.name for parameter in langgraph.parameters] == [
        "graph_name",
        "stream_mode",
    ]


def test_agent_persistence_capability_catalog_declares_langgraph_backends() -> None:
    capability = get_capability("agent-persistence")

    assert capability is not None
    assert capability.layer == "inbound"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("langgraph",)
    langgraph = capability.get_adapter("langgraph")
    assert langgraph is not None
    assert langgraph.config_path is None
    assert langgraph.entity_scoped is False
    assert [template.path for template in langgraph.merge_config_templates] == [
        "config/adapters/inbound/langgraph.yaml"
    ]
    assert langgraph.merge_config_templates[0].preserve_existing is True
    assert [parameter.name for parameter in langgraph.parameters] == [
        "mode",
        "checkpointer",
        "store",
        "checkpointer_setup",
        "store_setup",
        "ttl_seconds",
        "sqlite_path",
        "database",
        "namespace_template",
        "checkpointer_factory",
        "store_factory",
    ]


def test_repository_adapter_specs_include_config_and_parameters() -> None:
    capability = get_capability("repository")
    assert capability is not None

    mongodb = capability.get_adapter("mongodb")
    duckdb = capability.get_adapter("duckdb")
    mariadb = capability.get_adapter("mariadb")

    assert mongodb is not None
    assert mongodb.config_path == "config/adapters/outbound/mongodb.yaml"
    assert [parameter.name for parameter in mongodb.parameters] == [
        "db_name",
        "collection_name",
        "multitenant",
    ]
    assert [mapping.field_path for mapping in mongodb.secret_mappings] == [
        "adapters.mongodb.uri"
    ]
    assert [mapping.secret_key for mapping in mongodb.secret_mappings] == [
        "MONGODB_URI"
    ]
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


def test_storage_capability_catalog_declares_object_storage_adapters() -> None:
    capability = get_capability("storage")

    assert capability is not None
    assert capability.layer == "outbound"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("filesystem", "s3", "azure-blob", "gcs")

    filesystem = capability.get_adapter("filesystem")
    s3 = capability.get_adapter("s3")
    azure_blob = capability.get_adapter("azure-blob")
    gcs = capability.get_adapter("gcs")

    assert filesystem is not None
    assert filesystem.config_path == "config/adapters/outbound/storage.yaml"
    assert filesystem.entity_scoped is False
    assert [parameter.name for parameter in filesystem.parameters] == [
        "root_path",
        "prefix",
        "create_root",
        "multitenant",
    ]
    assert s3 is not None
    assert s3.config_path == "config/adapters/outbound/storage.yaml"
    assert [parameter.name for parameter in s3.parameters] == [
        "bucket_name",
        "prefix",
        "region_name",
        "endpoint_url",
        "force_path_style",
        "multitenant",
    ]
    assert azure_blob is not None
    assert azure_blob.config_path == "config/adapters/outbound/storage.yaml"
    assert [parameter.name for parameter in azure_blob.parameters] == [
        "account_url",
        "container_name",
        "prefix",
        "use_default_credential",
        "multitenant",
    ]
    assert [mapping.field_path for mapping in azure_blob.secret_mappings] == [
        "adapters.storage.connection_string",
        "adapters.storage.account_key",
        "adapters.storage.sas_token",
    ]
    assert [mapping.secret_key for mapping in azure_blob.secret_mappings] == [
        "AZURE_STORAGE_CONNECTION_STRING",
        "AZURE_STORAGE_ACCOUNT_KEY",
        "AZURE_STORAGE_SAS_TOKEN",
    ]
    assert gcs is not None
    assert gcs.config_path == "config/adapters/outbound/storage.yaml"
    assert [parameter.name for parameter in gcs.parameters] == [
        "bucket_name",
        "prefix",
        "project_id",
        "multitenant",
    ]


def test_capability_catalog_is_json_serializable() -> None:
    payload = capability_catalog_as_dict()

    encoded = json.dumps(payload)

    assert "repository" in encoded
    assert "mongodb" in encoded
    assert "storage" in encoded
    assert "filesystem" in encoded
    assert "azure-blob" in encoded
    assert "gcs" in encoded
    assert "cache" in encoded
    assert "redis" in encoded
    assert "logger" in encoded
    assert "console" in encoded
    assert "secrets" in encoded
    assert "env" in encoded
    assert "api" in encoded
    assert "fastapi" in encoded
    assert "mcp" in encoded
    assert "fastmcp" in encoded
    assert "probe" in encoded
    assert "server" in encoded
    assert "http" in encoded
    assert "idempotency" in encoded
    assert "etag" in encoded
    assert "cache-control" in encoded
    assert "command-bus" in encoded
    assert "rabbitmq" in encoded
    assert "runtime" in encoded
    assert "docker-image" in encoded
    assert "auth" in encoded
    assert "keycloak" in encoded
    assert "tenant" in encoded
    assert "license" in encoded
    assert "role" in encoded
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
    assert [adapter["name"] for adapter in repository["adapters"]] == [
        "memory",
        "mongodb",
        "duckdb",
        "mariadb",
        "postgresql",
    ]
    assert repository["adapters"][0]["entity_scoped"] is True
    assert repository["adapters"][0]["facets"] == {
        "storage_model": "memory",
        "runtime": "in_process",
        "production_ready": False,
        "multi_process": False,
        "transactions": "none",
        "schema_strategy": "flexible",
        "recommended_for": [
            "tests unitaires",
            "développement et smoke dans un seul processus",
        ],
        "limits": [
            "données perdues à l'arrêt",
            "état non partagé entre processus",
        ],
    }
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
    storage = payload_by_name["storage"]
    assert storage["layer"] == "outbound"
    assert storage["activation_config_key"] is None
    assert [adapter["name"] for adapter in storage["adapters"]] == [
        "filesystem",
        "s3",
        "azure-blob",
        "gcs",
    ]
    filesystem = storage["adapters"][0]
    assert filesystem["config_path"] == "config/adapters/outbound/storage.yaml"
    assert filesystem["entity_scoped"] is False
    assert filesystem["facets"] is None
    assert [parameter["name"] for parameter in filesystem["parameters"]] == [
        "root_path",
        "prefix",
        "create_root",
        "multitenant",
    ]
    s3 = storage["adapters"][1]
    assert s3["config_path"] == "config/adapters/outbound/storage.yaml"
    assert [parameter["name"] for parameter in s3["parameters"]] == [
        "bucket_name",
        "prefix",
        "region_name",
        "endpoint_url",
        "force_path_style",
        "multitenant",
    ]
    azure_blob = storage["adapters"][2]
    assert azure_blob["config_path"] == "config/adapters/outbound/storage.yaml"
    assert [parameter["name"] for parameter in azure_blob["parameters"]] == [
        "account_url",
        "container_name",
        "prefix",
        "use_default_credential",
        "multitenant",
    ]
    assert [mapping["field_path"] for mapping in azure_blob["secret_mappings"]] == [
        "adapters.storage.connection_string",
        "adapters.storage.account_key",
        "adapters.storage.sas_token",
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
    assert [
        mapping["field_path"] for mapping in cache["adapters"][1]["secret_mappings"]
    ] == ["cache.redis_url"]
    logger = payload_by_name["logger"]
    assert logger["activation_config_key"] == "logger"
    assert [adapter["name"] for adapter in logger["adapters"]] == ["console"]
    assert logger["adapters"][0]["entity_scoped"] is False
    assert logger["adapters"][0]["config_path"] is None
    secrets = payload_by_name["secrets"]
    assert [adapter["name"] for adapter in secrets["adapters"]] == [
        "env",
        "yaml",
        "vault",
        "chain",
    ]
    env = secrets["adapters"][0]
    yaml_adapter = secrets["adapters"][1]
    vault_adapter = secrets["adapters"][2]
    chain_adapter = secrets["adapters"][3]
    assert env["secret_resolver"] == "env"
    assert [parameter["name"] for parameter in env["parameters"]] == [
        "field_path",
        "secret_key",
    ]
    assert env["parameters"][0]["required"] is True
    assert yaml_adapter["secret_resolver"] == "yaml"
    assert yaml_adapter["gitignore_entries"] == ["secrets.yaml"]
    assert [template["path"] for template in yaml_adapter["file_templates"]] == [
        "secrets.yaml.template"
    ]
    assert vault_adapter["secret_resolver"] == "vault"
    assert [parameter["name"] for parameter in vault_adapter["parameters"]] == [
        "field_path",
        "secret_key",
        "addr",
        "mount",
    ]
    assert chain_adapter["secret_resolver"] == "chain"
    chain_parameters = {
        parameter["name"]: parameter for parameter in chain_adapter["parameters"]
    }
    assert chain_parameters["resolvers"]["choices"] == ["env", "vault", "yaml"]
    assert chain_parameters["resolvers"]["csv_choices"] is True
    assert [adapter["name"] for adapter in payload_by_name["api"]["adapters"]] == [
        "fastapi"
    ]
    assert [adapter["name"] for adapter in payload_by_name["mcp"]["adapters"]] == [
        "fastmcp"
    ]
    probe = payload_by_name["probe"]
    assert [adapter["name"] for adapter in probe["adapters"]] == ["server"]
    probe_server = probe["adapters"][0]
    assert probe_server["config_path"] == "config/adapters/inbound/probe.yaml"
    assert [parameter["name"] for parameter in probe_server["parameters"]] == [
        "host",
        "port",
        "enabled",
    ]
    http = payload_by_name["http"]
    assert [adapter["name"] for adapter in http["adapters"]] == [
        "idempotency",
        "etag",
        "cache-control",
    ]
    idempotency = http["adapters"][0]
    etag = http["adapters"][1]
    cache_control = http["adapters"][2]
    assert idempotency["config_path"] is None
    assert [template["path"] for template in idempotency["merge_config_templates"]] == [
        "config/http.yaml"
    ]
    assert [parameter["name"] for parameter in idempotency["parameters"]] == [
        "enabled",
        "ttl_seconds",
        "required",
    ]
    assert etag["config_path"] is None
    assert [template["path"] for template in etag["merge_config_templates"]] == [
        "config/http.yaml"
    ]
    assert [parameter["name"] for parameter in etag["parameters"]] == ["enabled"]
    assert cache_control["config_path"] is None
    assert [
        template["path"] for template in cache_control["merge_config_templates"]
    ] == ["config/http.yaml"]
    assert [parameter["name"] for parameter in cache_control["parameters"]] == [
        "get_single_max_age",
        "get_list_max_age",
    ]
    command_bus = payload_by_name["command-bus"]
    assert command_bus["layer"] == "bidirectional"
    assert [adapter["name"] for adapter in command_bus["adapters"]] == ["rabbitmq"]
    rabbitmq = command_bus["adapters"][0]
    assert rabbitmq["config_path"] is None
    assert [template["path"] for template in rabbitmq["merge_config_templates"]] == [
        "config/command_bus.yaml"
    ]
    assert [parameter["name"] for parameter in rabbitmq["parameters"]] == [
        "url",
        "exchange",
        "exchange_type",
        "queue",
        "routing_key",
        "prefetch",
        "consumer_name",
        "concurrency",
        "publisher_confirms",
        "durable",
        "retry_enabled",
        "retry_requeue",
        "dead_letter_exchange",
        "dead_letter_routing_key",
    ]
    channel = payload_by_name["channel"]
    assert channel["layer"] == "bidirectional"
    assert [adapter["name"] for adapter in channel["adapters"]] == [
        "memory",
        "webhook",
    ]
    memory_channel = channel["adapters"][0]
    assert memory_channel["config_path"] == (
        "config/adapters/bidirectional/memory.yaml"
    )
    assert memory_channel["dependency_extra"] is None
    webhook_channel = channel["adapters"][1]
    assert webhook_channel["config_path"] == (
        "config/adapters/bidirectional/webhook.yaml"
    )
    assert webhook_channel["dependency_extra"] == "channel"
    runtime = payload_by_name["runtime"]
    assert runtime["layer"] == "runtime"
    assert [adapter["name"] for adapter in runtime["adapters"]] == ["docker-image"]
    docker_image = runtime["adapters"][0]
    assert [template["path"] for template in docker_image["file_templates"]] == [
        "Dockerfile",
        ".dockerignore",
        "arclith-run",
    ]
    assert [parameter["name"] for parameter in docker_image["parameters"]] == [
        "uv_version",
        "api_port",
        "mcp_port",
        "probe_port",
        "agent_port",
    ]
    auth = payload_by_name["auth"]
    assert [adapter["name"] for adapter in auth["adapters"]] == ["keycloak"]
    keycloak_parameters = {
        parameter["name"]: parameter for parameter in auth["adapters"][0]["parameters"]
    }
    assert keycloak_parameters["url"]["default"] == "http://localhost:8080"
    assert keycloak_parameters["realm"]["default"] == "rekipe"
    assert keycloak_parameters["audience"]["default"] == "null"
    assert keycloak_parameters["client_id"]["default"] == "null"
    tenant = payload_by_name["tenant"]
    assert [adapter["name"] for adapter in tenant["adapters"]] == ["vault"]
    tenant_vault = tenant["adapters"][0]
    assert tenant_vault["config_path"] == "config/adapters/inbound/tenant.yaml"
    assert [
        template["path"] for template in tenant_vault["merge_config_templates"]
    ] == ["config/adapters/inbound/cache.yaml"]
    license_capability = payload_by_name["license"]
    assert [adapter["name"] for adapter in license_capability["adapters"]] == ["role"]
    role_parameters = {
        parameter["name"]: parameter
        for parameter in license_capability["adapters"][0]["parameters"]
    }
    assert (
        license_capability["adapters"][0]["config_path"]
        == "config/adapters/inbound/license.yaml"
    )
    assert role_parameters["role"]["default"] == "rekipe:licensed"
    llm = payload_by_name["llm"]
    assert [adapter["name"] for adapter in llm["adapters"]] == [
        "lmstudio",
        "openai",
        "anthropic",
    ]
    openai = llm["adapters"][1]
    openai_parameters = {
        parameter["name"]: parameter for parameter in openai["parameters"]
    }
    assert openai_parameters["model_name"]["default"] == "remplacer-par-model-id-openai"
    assert openai_parameters["api_key"]["secret"] is True
    assert openai_parameters["api_key"]["default"] == ""
    anthropic = llm["adapters"][2]
    anthropic_parameters = {
        parameter["name"]: parameter for parameter in anthropic["parameters"]
    }
    assert (
        anthropic_parameters["model_name"]["default"]
        == "remplacer-par-model-id-anthropic"
    )
    assert anthropic_parameters["api_key"]["secret"] is True
    assert anthropic_parameters["api_key"]["default"] == ""
    assert [adapter["name"] for adapter in payload_by_name["agent"]["adapters"]] == [
        "langgraph"
    ]
    observability = payload_by_name["observability"]
    assert [adapter["name"] for adapter in observability["adapters"]] == [
        "langsmith",
        "opentelemetry",
    ]
    langsmith = observability["adapters"][0]
    assert langsmith["dependency_extra"] == "langsmith"
    assert [profile["name"] for profile in langsmith["profiles"]] == [
        "development",
        "production",
    ]
