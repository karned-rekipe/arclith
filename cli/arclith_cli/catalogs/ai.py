from __future__ import annotations

from arclith_cli.capability_models import (
    AdapterSpec,
    CapabilitySpec,
    FileTemplateSpec,
    ParameterSpec,
    SecretMappingSpec,
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

EMBEDDING_CAPABILITY = CapabilitySpec(
    name="embedding",
    layer="outbound",
    description="Calcul de vecteurs texte derrière un port provider-neutral, sans persistance.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="deterministic",
            capability="embedding",
            layer="outbound",
            description="Vecteurs déterministes sans dépendance pour tests et smoke locaux.",
            config_path="config/adapters/outbound/embedding.yaml",
            config_template="""\
adapter: deterministic
model_name: "{model_name}"
dimensions: {dimensions}
batch_size: {batch_size}
normalize: {normalize}
multitenant: {multitenant}
""",
            parameters=(
                ParameterSpec(
                    name="model_name",
                    kind="string",
                    prompt="Nom du modèle déterministe",
                    default="deterministic-test",
                ),
                ParameterSpec(
                    name="dimensions",
                    kind="string",
                    prompt="Dimension des vecteurs",
                    default="1536",
                ),
                ParameterSpec(
                    name="batch_size",
                    kind="string",
                    prompt="Taille maximale des sous-batches",
                    default="64",
                ),
                ParameterSpec(
                    name="normalize",
                    kind="boolean",
                    prompt="Normaliser les vecteurs en norme L2",
                    default=True,
                ),
                ParameterSpec(
                    name="multitenant",
                    kind="boolean",
                    prompt="Réserver la résolution de contexte par tenant",
                    default=False,
                ),
            ),
            entity_scoped=False,
        ),
        AdapterSpec(
            name="openai-compatible",
            capability="embedding",
            layer="outbound",
            description="Endpoint local ou distant compatible OpenAI Embeddings.",
            config_path="config/adapters/outbound/embedding.yaml",
            config_template="""\
adapter: openai-compatible
base_url: "{base_url}"
api_key: "{api_key}"
model_name: "{model_name}"
dimensions: {dimensions}
batch_size: {batch_size}
timeout: {timeout}
normalize: {normalize}
multitenant: {multitenant}
""",
            parameters=(
                ParameterSpec(
                    name="base_url",
                    kind="string",
                    prompt="Base URL OpenAI-compatible avec préfixe API",
                    default="http://127.0.0.1:1234/v1",
                ),
                ParameterSpec(
                    name="api_key",
                    kind="string",
                    prompt="API key locale ou résolue par secrets",
                    default="local-dev",
                    secret=True,
                ),
                ParameterSpec(
                    name="model_name",
                    kind="string",
                    prompt="ID exact du modèle d'embedding exposé",
                    default="remplacer-par-model-id-embedding-local",
                ),
                ParameterSpec(
                    name="dimensions",
                    kind="string",
                    prompt="Dimension attendue des vecteurs",
                    default="1536",
                ),
                ParameterSpec(
                    name="batch_size",
                    kind="string",
                    prompt="Taille maximale des sous-batches",
                    default="64",
                ),
                ParameterSpec(
                    name="timeout",
                    kind="string",
                    prompt="Timeout HTTP en secondes",
                    default="30.0",
                ),
                ParameterSpec(
                    name="normalize",
                    kind="boolean",
                    prompt="Normaliser les vecteurs en norme L2",
                    default=False,
                ),
                ParameterSpec(
                    name="multitenant",
                    kind="boolean",
                    prompt="Réserver la résolution de contexte par tenant",
                    default=False,
                ),
            ),
            dependency_extra="embedding",
            entity_scoped=False,
        ),
        AdapterSpec(
            name="openai",
            capability="embedding",
            layer="outbound",
            description="Embeddings via l'API OpenAI officielle et un secret externe.",
            config_path="config/adapters/outbound/embedding.yaml",
            config_template="""\
adapter: openai
base_url: "{base_url}"
api_key: null
model_name: "{model_name}"
dimensions: {dimensions}
batch_size: {batch_size}
timeout: {timeout}
encoding_format: {encoding_format}
normalize: {normalize}
multitenant: {multitenant}
""",
            env_path=".env",
            env_template="""\
OPENAI_API_KEY={api_key}
""",
            secret_mappings=(
                SecretMappingSpec(
                    field_path="adapters.embedding.api_key",
                    secret_key="OPENAI_API_KEY",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="base_url",
                    kind="string",
                    prompt="Endpoint officiel OpenAI avec préfixe API",
                    default="https://api.openai.com/v1",
                ),
                ParameterSpec(
                    name="api_key",
                    kind="string",
                    prompt="OPENAI_API_KEY (laisser vide pour un secret externe)",
                    default="",
                    secret=True,
                ),
                ParameterSpec(
                    name="model_name",
                    kind="string",
                    prompt="ID du modèle d'embedding OpenAI accessible au projet",
                    default="remplacer-par-model-id-openai-embedding",
                ),
                ParameterSpec(
                    name="dimensions",
                    kind="string",
                    prompt="Dimension optionnelle des vecteurs (null pour le défaut modèle)",
                    default="null",
                ),
                ParameterSpec(
                    name="batch_size",
                    kind="string",
                    prompt="Taille maximale des sous-batches",
                    default="64",
                ),
                ParameterSpec(
                    name="timeout",
                    kind="string",
                    prompt="Timeout HTTP en secondes",
                    default="30.0",
                ),
                ParameterSpec(
                    name="encoding_format",
                    kind="string",
                    prompt="Format des vecteurs retournés",
                    default="float",
                    choices=("float",),
                ),
                ParameterSpec(
                    name="normalize",
                    kind="boolean",
                    prompt="Normaliser les vecteurs en norme L2",
                    default=False,
                ),
                ParameterSpec(
                    name="multitenant",
                    kind="boolean",
                    prompt="Réserver la résolution de contexte par tenant",
                    default=False,
                ),
            ),
            dependency_extra="embedding",
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
stream_mode: {stream_mode_yaml}
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
from langgraph.config import get_stream_writer
from langgraph.graph import END, START


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]


arclith = Arclith("config")


# Template minimal volontaire: remplacer AgentState, run_agent et les edges par
# l'état, les noeuds et les transitions propres au projet.
async def run_agent(state: AgentState) -> AgentState:
    writer = get_stream_writer()
    writer({{"kind": "progress", "stage": "agent.started", "message": "Agent node started."}})
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
                ParameterSpec(
                    name="stream_mode",
                    kind="string",
                    prompt="Mode(s) de streaming LangGraph",
                    default="updates",
                    choices=(
                        "values",
                        "updates",
                        "custom",
                        "messages",
                        "checkpoints",
                        "tasks",
                        "debug",
                    ),
                    csv_choices=True,
                ),
            ),
            entity_scoped=False,
        ),
    ),
)


AGENT_PERSISTENCE_CAPABILITY = CapabilitySpec(
    name="agent-persistence",
    layer="inbound",
    description="Checkpoints de threads et memoire cross-thread pour LangGraph.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="langgraph",
            capability="agent-persistence",
            layer="inbound",
            description="Persistance LangGraph optionnelle, configurable et extensible.",
            merge_config_templates=(
                FileTemplateSpec(
                    path="config/adapters/inbound/langgraph.yaml",
                    template="{persistence_config_yaml}\n",
                    preserve_existing=True,
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="mode",
                    kind="string",
                    prompt="Mode de persistance LangGraph",
                    default="auto",
                    choices=("auto", "embedded", "agent_server"),
                ),
                ParameterSpec(
                    name="checkpointer",
                    kind="string",
                    prompt="Backend de checkpoints",
                    default="memory",
                    choices=(
                        "none",
                        "memory",
                        "sqlite",
                        "postgresql",
                        "mongodb",
                        "custom",
                    ),
                ),
                ParameterSpec(
                    name="store",
                    kind="string",
                    prompt="Backend de memoire cross-thread",
                    default="memory",
                    choices=(
                        "none",
                        "memory",
                        "postgresql",
                        "mongodb",
                        "redis",
                        "custom",
                    ),
                ),
                ParameterSpec(
                    name="checkpointer_setup",
                    kind="boolean",
                    prompt="Executer setup() pour le checkpointer",
                    default=False,
                ),
                ParameterSpec(
                    name="store_setup",
                    kind="boolean",
                    prompt="Executer setup() pour le store",
                    default=False,
                ),
                ParameterSpec(
                    name="ttl_seconds",
                    kind="string",
                    prompt="TTL des checkpoints en secondes (vide = illimite)",
                    default="",
                ),
                ParameterSpec(
                    name="sqlite_path",
                    kind="string",
                    prompt="Fichier SQLite des checkpoints",
                    default=".arclith/langgraph-checkpoints.sqlite",
                ),
                ParameterSpec(
                    name="database",
                    kind="string",
                    prompt="Base de persistance LangGraph",
                    default="langgraph",
                ),
                ParameterSpec(
                    name="namespace_template",
                    kind="string",
                    prompt="Template de namespace long-term memory",
                    default="{tenant_id}:{user_id}:memories",
                ),
                ParameterSpec(
                    name="checkpointer_factory",
                    kind="string",
                    prompt="Import path de la factory custom checkpointer",
                    default="",
                ),
                ParameterSpec(
                    name="store_factory",
                    kind="string",
                    prompt="Import path de la factory custom store",
                    default="",
                ),
            ),
            entity_scoped=False,
        ),
    ),
)
