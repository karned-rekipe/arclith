from __future__ import annotations

from arclith_cli.capability_models import (
    AdapterSpec,
    CapabilitySpec,
    FileTemplateSpec,
    ParameterSpec,
)
from arclith_cli.runtime_templates import (
    ARCLITH_RUN_TEMPLATE,
    DEFAULT_AGENT_PORT,
    DEFAULT_API_PORT,
    DEFAULT_MCP_PORT,
    DEFAULT_PROBE_PORT,
    DEFAULT_UV_VERSION,
    DOCKERFILE_TEMPLATE,
    DOCKERIGNORE_TEMPLATE,
)

API_CAPABILITY = CapabilitySpec(
    name="api",
    layer="inbound",
    description="Transport HTTP REST expose via FastAPI.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="fastapi",
            capability="api",
            layer="inbound",
            description="Application FastAPI configurée par Arclith.fastapi().",
            config_path="config/adapters/inbound/fastapi.yaml",
            config_template="""\
host: {host}
port: {port}
reload: {reload}
""",
            parameters=(
                ParameterSpec(
                    name="host",
                    kind="string",
                    prompt="Host FastAPI",
                    default="0.0.0.0",
                ),
                ParameterSpec(
                    name="port",
                    kind="string",
                    prompt="Port FastAPI",
                    default="8000",
                ),
                ParameterSpec(
                    name="reload",
                    kind="boolean",
                    prompt="Activer le reload FastAPI",
                    default=True,
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

MCP_CAPABILITY = CapabilitySpec(
    name="mcp",
    layer="inbound",
    description="Transport MCP expose via FastMCP.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="fastmcp",
            capability="mcp",
            layer="inbound",
            description="Serveur FastMCP configuré par Arclith.fastmcp() et les runners MCP.",
            config_path="config/adapters/inbound/fastmcp.yaml",
            config_template="""\
host: {host}
port: {port}
""",
            parameters=(
                ParameterSpec(
                    name="host",
                    kind="string",
                    prompt="Host FastMCP",
                    default="127.0.0.1",
                ),
                ParameterSpec(
                    name="port",
                    kind="string",
                    prompt="Port FastMCP",
                    default="8001",
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

PROBE_CAPABILITY = CapabilitySpec(
    name="probe",
    layer="inbound",
    description="Serveur de probes health, readiness, info et metrics.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="server",
            capability="probe",
            layer="inbound",
            description="Serveur HTTP transverse exposant /health, /ready, /info et /metrics.",
            config_path="config/adapters/inbound/probe.yaml",
            config_template="""\
host: {host}
port: {port}
enabled: {enabled}
""",
            parameters=(
                ParameterSpec(
                    name="host",
                    kind="string",
                    prompt="Host du serveur de probes",
                    default="0.0.0.0",
                ),
                ParameterSpec(
                    name="port",
                    kind="string",
                    prompt="Port du serveur de probes",
                    default="9000",
                ),
                ParameterSpec(
                    name="enabled",
                    kind="boolean",
                    prompt="Activer le serveur de probes",
                    default=True,
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

HTTP_CAPABILITY = CapabilitySpec(
    name="http",
    layer="inbound",
    description="Middlewares HTTP transverses pour FastAPI.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="idempotency",
            capability="http",
            layer="inbound",
            description="Middleware Idempotency-Key pour éviter les doubles mutations POST.",
            merge_config_templates=(
                FileTemplateSpec(
                    path="config/http.yaml",
                    template="""\
idempotency:
  enabled: {enabled}
  ttl_seconds: {ttl_seconds}
  required: {required}
""",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="enabled",
                    kind="boolean",
                    prompt="Activer le middleware idempotency",
                    default=True,
                ),
                ParameterSpec(
                    name="ttl_seconds",
                    kind="string",
                    prompt="TTL idempotency en secondes",
                    default="86400",
                ),
                ParameterSpec(
                    name="required",
                    kind="boolean",
                    prompt="Exiger Idempotency-Key sur les POST",
                    default=False,
                ),
            ),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="etag",
            capability="http",
            layer="inbound",
            description="Middleware ETag et If-None-Match pour les lectures GET cacheables.",
            merge_config_templates=(
                FileTemplateSpec(
                    path="config/http.yaml",
                    template="""\
etag:
  enabled: {enabled}
""",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="enabled",
                    kind="boolean",
                    prompt="Activer le middleware ETag",
                    default=True,
                ),
            ),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="cache-control",
            capability="http",
            layer="inbound",
            description="Directives Cache-Control FastAPI pour lectures GET et mutations.",
            merge_config_templates=(
                FileTemplateSpec(
                    path="config/http.yaml",
                    template="""\
cache_control:
  get_single_max_age: {get_single_max_age}
  get_list_max_age: {get_list_max_age}
""",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="get_single_max_age",
                    kind="string",
                    prompt="TTL Cache-Control des GET ressource unique",
                    default="300",
                ),
                ParameterSpec(
                    name="get_list_max_age",
                    kind="string",
                    prompt="TTL Cache-Control des GET collection",
                    default="60",
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

COMMAND_BUS_CAPABILITY = CapabilitySpec(
    name="command-bus",
    layer="bidirectional",
    description="Bus de commandes applicatives use-case first.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="rabbitmq",
            capability="command-bus",
            layer="bidirectional",
            description="Worker et publisher RabbitMQ avec ack manuel, confirms, prefetch borne et DLX.",
            merge_config_templates=(
                FileTemplateSpec(
                    path="config/command_bus.yaml",
                    template="""\
enabled:
  - rabbitmq
rabbitmq:
  url: "{url}"
  exchange: "{exchange}"
  exchange_type: "{exchange_type}"
  queue: "{queue}"
  routing_key: "{routing_key}"
  prefetch: {prefetch}
  consumer_name: "{consumer_name}"
  concurrency: {concurrency}
  publisher_confirms: {publisher_confirms}
  durable: {durable}
  retry_enabled: {retry_enabled}
  retry_requeue: {retry_requeue}
  dead_letter_exchange: "{dead_letter_exchange}"
  dead_letter_routing_key: "{dead_letter_routing_key}"
""",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="url",
                    kind="string",
                    prompt="URL RabbitMQ",
                    default="amqp://guest:guest@127.0.0.1:5672/",
                ),
                ParameterSpec(
                    name="exchange",
                    kind="string",
                    prompt="Exchange commandes",
                    default="arclith.commands",
                ),
                ParameterSpec(
                    name="exchange_type",
                    kind="string",
                    prompt="Type d'exchange",
                    default="topic",
                    choices=("direct", "topic"),
                ),
                ParameterSpec(
                    name="queue",
                    kind="string",
                    prompt="Queue worker",
                    default="arclith.commands",
                ),
                ParameterSpec(
                    name="routing_key",
                    kind="string",
                    prompt="Routing key",
                    default="commands",
                ),
                ParameterSpec(
                    name="prefetch",
                    kind="string",
                    prompt="Prefetch RabbitMQ borne",
                    default="10",
                ),
                ParameterSpec(
                    name="consumer_name",
                    kind="string",
                    prompt="Consumer name",
                    default="arclith-command-worker",
                ),
                ParameterSpec(
                    name="concurrency",
                    kind="string",
                    prompt="Concurrence worker",
                    default="1",
                ),
                ParameterSpec(
                    name="publisher_confirms",
                    kind="boolean",
                    prompt="Activer publisher confirms",
                    default=True,
                ),
                ParameterSpec(
                    name="durable",
                    kind="boolean",
                    prompt="Déclarer exchange/queue durables",
                    default=True,
                ),
                ParameterSpec(
                    name="retry_enabled",
                    kind="boolean",
                    prompt="Activer DLX/retry",
                    default=True,
                ),
                ParameterSpec(
                    name="retry_requeue",
                    kind="boolean",
                    prompt="Requeue sur erreur handler",
                    default=False,
                ),
                ParameterSpec(
                    name="dead_letter_exchange",
                    kind="string",
                    prompt="Exchange DLX",
                    default="arclith.commands.dlx",
                ),
                ParameterSpec(
                    name="dead_letter_routing_key",
                    kind="string",
                    prompt="Routing key DLX",
                    default="commands.dead",
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

RUNTIME_CAPABILITY = CapabilitySpec(
    name="runtime",
    layer="runtime",
    description="Runtime de déploiement standardisé pour images et processus Arclith.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="docker-image",
            capability="runtime",
            layer="runtime",
            description="Dockerfile multi-stage non-root et entrypoint arclith-run multi-transport.",
            file_templates=(
                FileTemplateSpec(path="Dockerfile", template=DOCKERFILE_TEMPLATE),
                FileTemplateSpec(path=".dockerignore", template=DOCKERIGNORE_TEMPLATE),
                FileTemplateSpec(path="arclith-run", template=ARCLITH_RUN_TEMPLATE),
            ),
            parameters=(
                ParameterSpec(
                    name="uv_version",
                    kind="string",
                    prompt="Version uv pinnee dans le builder Docker",
                    default=DEFAULT_UV_VERSION,
                ),
                ParameterSpec(
                    name="api_port",
                    kind="string",
                    prompt="Port expose FastAPI",
                    default=DEFAULT_API_PORT,
                ),
                ParameterSpec(
                    name="mcp_port",
                    kind="string",
                    prompt="Port expose FastMCP",
                    default=DEFAULT_MCP_PORT,
                ),
                ParameterSpec(
                    name="probe_port",
                    kind="string",
                    prompt="Port expose probes /health",
                    default=DEFAULT_PROBE_PORT,
                ),
                ParameterSpec(
                    name="agent_port",
                    kind="string",
                    prompt="Port expose LangGraph agent",
                    default=DEFAULT_AGENT_PORT,
                ),
            ),
            entity_scoped=False,
        ),
    ),
)
