from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ParameterKind = Literal["string", "boolean"]
LayerKind = Literal["inbound", "outbound"]


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    kind: ParameterKind
    prompt: str
    default: str | bool | None = None
    default_from_project_name: bool = False
    secret: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "prompt": self.prompt,
            "default": self.default,
            "default_from_project_name": self.default_from_project_name,
            "secret": self.secret,
        }


@dataclass(frozen=True)
class FileTemplateSpec:
    path: str
    template: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
        }


@dataclass(frozen=True)
class SecretMappingSpec:
    field_path: str
    secret_key: str

    def to_dict(self) -> dict[str, str]:
        return {
            "field_path": self.field_path,
            "secret_key": self.secret_key,
        }


@dataclass(frozen=True)
class AdapterSpec:
    name: str
    capability: str
    layer: LayerKind
    description: str
    config_path: str | None = None
    config_template: str = ""
    env_path: str | None = None
    env_template: str = ""
    file_templates: tuple[FileTemplateSpec, ...] = ()
    secret_mappings: tuple[SecretMappingSpec, ...] = ()
    parameters: tuple[ParameterSpec, ...] = ()
    entity_scoped: bool = True

    def has_config(self) -> bool:
        return self.config_path is not None and bool(self.config_template)

    def has_env(self) -> bool:
        return self.env_path is not None and bool(self.env_template)

    def has_file_templates(self) -> bool:
        return bool(self.file_templates)

    def has_secret_mappings(self) -> bool:
        return bool(self.secret_mappings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "capability": self.capability,
            "layer": self.layer,
            "description": self.description,
            "config_path": self.config_path,
            "env_path": self.env_path,
            "file_templates": [file_template.to_dict() for file_template in self.file_templates],
            "secret_mappings": [secret_mapping.to_dict() for secret_mapping in self.secret_mappings],
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "entity_scoped": self.entity_scoped,
        }


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    layer: LayerKind
    description: str
    activation_config_key: str | None
    adapters: tuple[AdapterSpec, ...]

    def adapter_names(self) -> tuple[str, ...]:
        return tuple(adapter.name for adapter in self.adapters)

    def get_adapter(self, name: str) -> AdapterSpec | None:
        normalized = name.strip().lower()
        for adapter in self.adapters:
            if adapter.name == normalized:
                return adapter
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "layer": self.layer,
            "description": self.description,
            "activation_config_key": self.activation_config_key,
            "adapters": [adapter.to_dict() for adapter in self.adapters],
        }


REPOSITORY_CAPABILITY = CapabilitySpec(
    name="repository",
    layer="outbound",
    description="Persistance des entités métier derrière un port repository.",
    activation_config_key="repository",
    adapters=(
        AdapterSpec(
            name="memory",
            capability="repository",
            layer="outbound",
            description="Stockage volatile en mémoire pour dev, tests et smoke locaux.",
        ),
        AdapterSpec(
            name="mongodb",
            capability="repository",
            layer="outbound",
            description="Repository MongoDB async avec configuration single-tenant ou multitenant.",
            config_path="config/adapters/outbound/mongodb.yaml",
            config_template="""\
uri: null   # single-tenant: mappez adapters.mongodb.uri via config/secrets.yaml, env ou Vault
db_name: {db_name}   # fallback multitenant si le secret tenant ne fournit pas db_name
collection_name: {collection_name}   # null = nom dérivé de la classe entité
multitenant: {multitenant}   # true = uri/db_name résolus par requête via JWT -> VaultTenantResolver
""",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="adapters.mongodb.uri",
                    secret_key="MONGODB_URI",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="db_name",
                    kind="string",
                    prompt="db_name",
                    default_from_project_name=True,
                ),
                ParameterSpec(
                    name="collection_name",
                    kind="string",
                    prompt="collection_name",
                    default="null",
                ),
                ParameterSpec(
                    name="multitenant",
                    kind="boolean",
                    prompt="multitenant",
                    default=False,
                ),
            ),
        ),
        AdapterSpec(
            name="duckdb",
            capability="repository",
            layer="outbound",
            description="Repository fichier local pour SQL analytique et démos sans serveur.",
            config_path="config/adapters/outbound/duckdb.yaml",
            config_template="""\
multitenant: false
path: {path}
""",
            parameters=(
                ParameterSpec(
                    name="path",
                    kind="string",
                    prompt="path",
                    default="data/",
                ),
            ),
        ),
        AdapterSpec(
            name="mariadb",
            capability="repository",
            layer="outbound",
            description="Repository MariaDB async optionnel, pilote par SQLAlchemy et asyncmy.",
            config_path="config/adapters/outbound/mariadb.yaml",
            config_template="""\
url: null   # à mapper via config/secrets.yaml ou resolver env/vault si vous fournissez une URL complète
host: {host}
port: {port}
database: {database}
user: {user}
password: null   # à mapper via config/secrets.yaml ou resolver env/vault
driver: {driver}
table_prefix: "{table_prefix}"
multitenant: false
""",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="adapters.mariadb.url",
                    secret_key="MARIADB_URL",
                ),
                SecretMappingSpec(
                    field_path="adapters.mariadb.password",
                    secret_key="MARIADB_PASSWORD",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="host",
                    kind="string",
                    prompt="host",
                    default="127.0.0.1",
                ),
                ParameterSpec(
                    name="port",
                    kind="string",
                    prompt="port",
                    default="3306",
                ),
                ParameterSpec(
                    name="database",
                    kind="string",
                    prompt="database",
                    default_from_project_name=True,
                ),
                ParameterSpec(
                    name="user",
                    kind="string",
                    prompt="user",
                    default="app",
                ),
                ParameterSpec(
                    name="driver",
                    kind="string",
                    prompt="driver",
                    default="asyncmy",
                ),
                ParameterSpec(
                    name="table_prefix",
                    kind="string",
                    prompt="table_prefix",
                    default="",
                ),
            ),
        ),
    ),
)

CACHE_CAPABILITY = CapabilitySpec(
    name="cache",
    layer="outbound",
    description="Cache transverse pour JWT JWKS, idempotency et résolution tenant.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="memory",
            capability="cache",
            layer="outbound",
            description="Cache local par processus pour dev, tests et exécution mono-worker.",
            config_path="config/adapters/inbound/cache.yaml",
            config_template="""\
backend: memory
jwks_ttl: {jwks_ttl}
tenant_uri_ttl: {tenant_uri_ttl}
""",
            parameters=(
                ParameterSpec(
                    name="jwks_ttl",
                    kind="string",
                    prompt="TTL JWKS en secondes",
                    default="3600",
                ),
                ParameterSpec(
                    name="tenant_uri_ttl",
                    kind="string",
                    prompt="TTL tenant en secondes",
                    default="300",
                ),
            ),
            entity_scoped=False,
        ),
    ),
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

LLM_CAPABILITY = CapabilitySpec(
    name="llm",
    layer="outbound",
    description="Configuration LLM pour interpréteurs d'intention et agents via une factory Arclith.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="lmstudio",
            capability="llm",
            layer="outbound",
            description="LLM local LM Studio exposé par l'API OpenAI-compatible.",
            config_path="config/adapters/outbound/lm.yaml",
            config_template="""\
provider: openai
model_name: "{model_name}"
api_key: "{api_key}"
base_url: "{base_url}"
""",
            parameters=(
                ParameterSpec(
                    name="model_name",
                    kind="string",
                    prompt="Model ID LM Studio",
                    default="remplacer-par-le-model-id-lm-studio",
                ),
                ParameterSpec(
                    name="base_url",
                    kind="string",
                    prompt="Endpoint OpenAI-compatible LM Studio",
                    default="http://127.0.0.1:1234/v1",
                ),
                ParameterSpec(
                    name="api_key",
                    kind="string",
                    prompt="API key LM Studio",
                    default="lm-studio",
                    secret=True,
                ),
            ),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="openai",
            capability="llm",
            layer="outbound",
            description="Modèle OpenAI via protocole OpenAI-compatible.",
            config_path="config/adapters/outbound/lm.yaml",
            config_template="""\
provider: openai
model_name: "{model_name}"
api_key: ""
base_url: "{base_url}"
""",
            env_path=".env",
            env_template="""\
OPENAI_API_KEY={api_key}
""",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="adapters.lm.api_key",
                    secret_key="OPENAI_API_KEY",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="model_name",
                    kind="string",
                    prompt="Modèle OpenAI",
                    default="remplacer-par-model-id-openai",
                ),
                ParameterSpec(
                    name="base_url",
                    kind="string",
                    prompt="Endpoint OpenAI-compatible",
                    default="https://api.openai.com/v1",
                ),
                ParameterSpec(
                    name="api_key",
                    kind="string",
                    prompt="OPENAI_API_KEY",
                    default="",
                    secret=True,
                ),
            ),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="anthropic",
            capability="llm",
            layer="outbound",
            description="Modèle Anthropic pour interpréteurs d'intention et agents.",
            config_path="config/adapters/outbound/lm.yaml",
            config_template="""\
provider: anthropic
model_name: "{model_name}"
api_key: ""
""",
            env_path=".env",
            env_template="""\
ANTHROPIC_API_KEY={api_key}
""",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="adapters.lm.api_key",
                    secret_key="ANTHROPIC_API_KEY",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="model_name",
                    kind="string",
                    prompt="Modèle Anthropic",
                    default="remplacer-par-model-id-anthropic",
                ),
                ParameterSpec(
                    name="api_key",
                    kind="string",
                    prompt="ANTHROPIC_API_KEY",
                    default="",
                    secret=True,
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

AGENT_CAPABILITY = CapabilitySpec(
    name="agent",
    layer="inbound",
    description="Adapter agent qui expose les cas d'usage métier via un runtime IA.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="langgraph",
            capability="agent",
            layer="inbound",
            description="Entrypoint LangGraph Studio basé sur la tuyauterie Arclith.",
            config_path="config/adapters/inbound/langgraph.yaml",
            config_template="""\
name: "{graph_name}"
graph: "{graph_name}"
entrypoint: "{langgraph_entrypoint}"
env: ".env"
""",
            file_templates=(
                FileTemplateSpec(
                    path="langgraph.json",
                    template="""\
{{
  "dependencies": ["."],
  "graphs": {{
    "{graph_name}": "{langgraph_entrypoint}"
  }},
  "env": ".env"
}}
""",
                ),
                FileTemplateSpec(
                    path="{package_path}/adapters/inbound/langgraph/__init__.py",
                    template="",
                ),
                FileTemplateSpec(
                    path="{package_path}/adapters/inbound/langgraph/agent.py",
                    template="""\
from typing import Any, TypedDict

from arclith import Arclith
from langgraph.graph import END, START


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]


arclith = Arclith("config")


# Template minimal volontaire: remplacer AgentState, run_agent et les edges par
# l'état, les noeuds et les transitions propres au projet.
async def run_agent(state: AgentState) -> AgentState:
    return state


def register_agent(builder: Any, app: Arclith) -> None:
    builder.add_node("agent", run_agent)
    builder.add_edge(START, "agent")
    builder.add_edge("agent", END)


agent = arclith.langgraph(AgentState, register_agent, name="{graph_name}")
""",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="graph_name",
                    kind="string",
                    prompt="Nom du graphe LangGraph",
                    default="agent",
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

OBSERVABILITY_CAPABILITY = CapabilitySpec(
    name="observability",
    layer="outbound",
    description="Observabilité activable en parallèle via LangSmith et OpenTelemetry.",
    activation_config_key="observability",
    adapters=(
        AdapterSpec(
            name="langsmith",
            capability="observability",
            layer="outbound",
            description="Tracing LangSmith et tests agent dans LangGraph Studio.",
            config_path="config/adapters/outbound/langsmith.yaml",
            config_template="""\
tracing: {tracing}
project: "{project}"
endpoint: "{endpoint}"
api_key_env: LANGSMITH_API_KEY
# Définir LANGSMITH_API_KEY hors Git: .env local, env runtime ou secret manager.
studio: langgraph
langgraph_api_min_version: "0.11.0"
""",
            env_path=".env",
            env_template="""\
LANGSMITH_TRACING={tracing}
LANGSMITH_PROJECT={project}
LANGSMITH_ENDPOINT={endpoint}
LANGSMITH_API_KEY={api_key}
""",
            parameters=(
                ParameterSpec(
                    name="tracing",
                    kind="boolean",
                    prompt="Activer LANGSMITH_TRACING",
                    default=True,
                ),
                ParameterSpec(
                    name="project",
                    kind="string",
                    prompt="Projet LangSmith",
                    default_from_project_name=True,
                ),
                ParameterSpec(
                    name="endpoint",
                    kind="string",
                    prompt="Endpoint LangSmith",
                    default="https://api.smith.langchain.com",
                ),
                ParameterSpec(
                    name="api_key",
                    kind="string",
                    prompt="LANGSMITH_API_KEY",
                    default="",
                    secret=True,
                ),
            ),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="opentelemetry",
            capability="observability",
            layer="outbound",
            description="Export OTLP traces/metrics et instrumentation FastAPI.",
            config_path="config/adapters/outbound/opentelemetry.yaml",
            config_template="""\
service_name: "{service_name}"
endpoint: "{endpoint}"
traces_endpoint: {traces_endpoint}
metrics_endpoint: {metrics_endpoint}
protocol: "{protocol}"
headers_env: OTEL_EXPORTER_OTLP_HEADERS
traces: {traces}
metrics: {metrics}
instrument_fastapi: {instrument_fastapi}
metrics_export_interval_millis: {metrics_export_interval_millis}
""",
            env_path=".env",
            env_template="""\
OTEL_SERVICE_NAME={service_name}
OTEL_EXPORTER_OTLP_ENDPOINT={endpoint}
OTEL_EXPORTER_OTLP_PROTOCOL={protocol}
OTEL_EXPORTER_OTLP_HEADERS={headers}
""",
            parameters=(
                ParameterSpec(
                    name="service_name",
                    kind="string",
                    prompt="OTEL_SERVICE_NAME",
                    default_from_project_name=True,
                ),
                ParameterSpec(
                    name="endpoint",
                    kind="string",
                    prompt="OTLP endpoint",
                    default="http://localhost:4318",
                ),
                ParameterSpec(
                    name="traces_endpoint",
                    kind="string",
                    prompt="OTLP traces endpoint",
                    default="null",
                ),
                ParameterSpec(
                    name="metrics_endpoint",
                    kind="string",
                    prompt="OTLP metrics endpoint",
                    default="null",
                ),
                ParameterSpec(
                    name="protocol",
                    kind="string",
                    prompt="OTLP protocol",
                    default="http/protobuf",
                ),
                ParameterSpec(
                    name="traces",
                    kind="boolean",
                    prompt="Exporter les traces",
                    default=True,
                ),
                ParameterSpec(
                    name="metrics",
                    kind="boolean",
                    prompt="Exporter les métriques",
                    default=False,
                ),
                ParameterSpec(
                    name="instrument_fastapi",
                    kind="boolean",
                    prompt="Instrumenter FastAPI",
                    default=True,
                ),
                ParameterSpec(
                    name="metrics_export_interval_millis",
                    kind="string",
                    prompt="Intervalle export métriques en ms",
                    default="60000",
                ),
                ParameterSpec(
                    name="headers",
                    kind="string",
                    prompt="OTEL_EXPORTER_OTLP_HEADERS",
                    default="",
                    secret=True,
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

CAPABILITY_CATALOG = (
    REPOSITORY_CAPABILITY,
    CACHE_CAPABILITY,
    API_CAPABILITY,
    MCP_CAPABILITY,
    LLM_CAPABILITY,
    AGENT_CAPABILITY,
    OBSERVABILITY_CAPABILITY,
)


def get_capability(name: str) -> CapabilitySpec | None:
    normalized = name.strip().lower()
    for capability in CAPABILITY_CATALOG:
        if capability.name == normalized:
            return capability
    return None


def capability_names() -> tuple[str, ...]:
    return tuple(capability.name for capability in CAPABILITY_CATALOG)


def repository_adapter_names() -> tuple[str, ...]:
    return REPOSITORY_CAPABILITY.adapter_names()


def capability_catalog_as_dict() -> list[dict[str, Any]]:
    return [capability.to_dict() for capability in CAPABILITY_CATALOG]
