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
    parameters: tuple[ParameterSpec, ...] = ()
    entity_scoped: bool = True

    def has_config(self) -> bool:
        return self.config_path is not None and bool(self.config_template)

    def has_env(self) -> bool:
        return self.env_path is not None and bool(self.env_template)

    def has_file_templates(self) -> bool:
        return bool(self.file_templates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "capability": self.capability,
            "layer": self.layer,
            "description": self.description,
            "config_path": self.config_path,
            "env_path": self.env_path,
            "file_templates": [file_template.to_dict() for file_template in self.file_templates],
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
    description="Persistance des entites metier derriere un port repository.",
    activation_config_key="repository",
    adapters=(
        AdapterSpec(
            name="memory",
            capability="repository",
            layer="outbound",
            description="Stockage volatile en memoire pour dev, tests et smoke locaux.",
        ),
        AdapterSpec(
            name="mongodb",
            capability="repository",
            layer="outbound",
            description="Repository MongoDB async avec configuration single-tenant ou multitenant.",
            config_path="config/adapters/outbound/mongodb.yaml",
            config_template="""\
multitenant: {multitenant}   # true = URI + db_name resolus par requete via JWT -> Vault
db_name: {db_name}   # uri -> secrets.yaml ou Vault (fallback single-tenant)
""",
            parameters=(
                ParameterSpec(
                    name="db_name",
                    kind="string",
                    prompt="db_name",
                    default_from_project_name=True,
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
            description="Repository fichier local pour SQL analytique et demos sans serveur.",
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
host: {host}
port: {port}
database: {database}
user: {user}
password: null   # a mapper via config/secrets.yaml ou resolver env/vault
driver: {driver}
table_prefix: "{table_prefix}"
multitenant: false
""",
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

AGENT_CAPABILITY = CapabilitySpec(
    name="agent",
    layer="inbound",
    description="Adapter agent qui expose les cas d'usage metier via un runtime IA.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="langgraph",
            capability="agent",
            layer="inbound",
            description="Entrypoint LangGraph Studio base sur la tuyauterie Arclith.",
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
    description="Observabilite et boucle de test agent via LangSmith Studio.",
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
    ),
)

CAPABILITY_CATALOG = (REPOSITORY_CAPABILITY, AGENT_CAPABILITY, OBSERVABILITY_CAPABILITY)


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
