# Capability Agent

Runtime agent basé sur LangGraph.

## Objectif

Un agent est un adapter inbound. Il reçoit une intention utilisateur, maintient
un état de graphe, puis appelle les ports inbound ou use cases Arclith.

## Adapter

| Adapter | Usage |
|---|---|
| `langgraph` | Agent Server local ou déployé, consommable par API |

## Commande

```bash
uv add "arclith[langgraph]"
arclith-cli add-adapter --capability agent --adapter langgraph --yes
```

## Fichiers Générés

```text
langgraph.json
config/adapters/inbound/langgraph.yaml
src/<package>/adapters/inbound/langgraph/agent.py
```

## Configuration Générée

```yaml
# config/adapters/inbound/langgraph.yaml
name: "agent"
graph: "agent"
entrypoint: "src/<package>/adapters/inbound/langgraph/agent.py:agent"
env: ".env"
stream_mode: "updates"
```

```json
{
  "dependencies": ["."],
  "graphs": {
    "agent": "src/<package>/adapters/inbound/langgraph/agent.py:agent"
  },
  "env": ".env"
}
```

## Créer Un Graphe

```python
from typing import Any, TypedDict

from arclith import Arclith
from langgraph.config import get_stream_writer
from langgraph.graph import END, START


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]


arclith = Arclith("config")


async def run_agent(state: AgentState) -> AgentState:
    writer = get_stream_writer()
    writer({"kind": "progress", "stage": "agent.started", "message": "Agent node started."})
    return state


def register_agent(builder: Any, app: Arclith) -> None:
    builder.add_node("agent", run_agent)
    builder.add_edge(START, "agent")
    builder.add_edge("agent", END)


agent = arclith.langgraph(AgentState, register_agent, name="agent")
```

Le template généré est volontairement minimal. Le projet remplace ensuite
`AgentState`, les nodes et les edges par son propre parcours.

## Threads Et Mémoire Durable

La capability optionnelle [agent-persistence](agent-persistence.md) câble les checkpointers de
threads et les stores cross-thread sans boilerplate projet :

```bash
arclith-cli add-adapter \
  --capability agent-persistence \
  --adapter langgraph \
  --param checkpointer=memory \
  --param store=memory \
  --yes
uv sync
```

`memory` convient aux tests. SQLite permet un debug local reproductible ; PostgreSQL, MongoDB et
Redis sont disponibles via des extras séparés pour la production.

## Streaming Et Progression

`config/adapters/inbound/langgraph.yaml` peut fixer le mode de streaming par
défaut du graphe compilé:

```yaml
stream_mode:
  - updates
  - custom
```

Le CLI accepte la même configuration via:

```bash
arclith-cli add-adapter \
  --capability agent \
  --adapter langgraph \
  --param stream_mode=updates,custom \
  --yes
```

Les modes utiles sont:

| Mode | Usage |
|---|---|
| `updates` | suivre les sorties de nodes |
| `values` | recevoir l'état complet après chaque étape |
| `messages` | streamer les tokens LLM quand le node utilise un modèle compatible |
| `custom` | recevoir les événements envoyés avec `get_stream_writer()` |

Dans un node qui consomme `LLMPort.stream_structured()`, publier les événements
Arclith en `custom`:

```python
from arclith.domain.ports.outbound.llm import llm_stream_event_to_payload
from langgraph.config import get_stream_writer


async def classify_intent(state: AgentState) -> AgentState:
    writer = get_stream_writer()
    final_intent = None

    async for event in llm.stream_structured(
        state["messages"][-1]["content"],
        output_type=Intent,
        instructions="Extraire l'intention utilisateur.",
    ):
        writer(llm_stream_event_to_payload(event))
        if event.kind == "structured_final":
            final_intent = event.output

    return {**state, "intent": final_intent}
```

## Appeler Le Métier

Un node peut appeler un use case injecté par le container du projet :

```python
async def create_todo(state: AgentState) -> AgentState:
    command = CreateTodoCommand(title=state["draft"]["title"])
    todo = await create_todo_use_case.execute(command)
    return {**state, "created_uuid": str(todo.uuid)}
```

Le LLM sert à interpréter ou choisir une action. Il ne persiste pas directement.

## LLM Et Observabilité

```bash
arclith-cli add-adapter --capability llm --adapter lmstudio --yes
arclith-cli add-adapter --capability observability --adapter langsmith --yes
```

LM Studio est pratique pour le local. LangSmith est optionnel mais utile pour
inspecter les runs, messages et erreurs.

Pour un développement hors ligne:

```bash
unset LANGSMITH_API_KEY LANGCHAIN_API_KEY
export LANGSMITH_TRACING=false
export LANGGRAPH_CLI_NO_ANALYTICS=1
```

LangGraph Studio charge une UI hébergée. Sans internet, interagir avec l'Agent Server via son API
locale ou via `langgraph_sdk`.

## Règles

- Un node appelle un use case ou un port inbound.
- Un node ne doit pas instancier de repository concret.
- L'état du graphe doit rester explicite et typé.
- Les chemins déterministes doivent éviter l'appel LLM quand c'est fiable.
- Les secrets LLM et LangSmith restent dans `.env` ou dans la capability [secrets](secrets.md).

## Validation

```bash
uv run langgraph dev
```

Pour un lancement sans navigateur :

```bash
uv run langgraph dev --no-browser --allow-blocking --port 2024
```

API locale:

```text
http://127.0.0.1:2024
http://127.0.0.1:2024/docs
```

Run rapide:

```bash
curl -N -X POST "http://127.0.0.1:2024/runs/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "agent",
    "input": {
      "messages": [
        {"role": "human", "content": "Réponds en une phrase."}
      ]
    },
    "stream_mode": "values"
  }'
```

Inspection durable:

```bash
THREAD_ID=$(curl -fsS -X POST "http://127.0.0.1:2024/threads" \
  -H "Content-Type: application/json" \
  -d '{}' | python -c 'import json,sys; print(json.load(sys.stdin)["thread_id"])')

curl -N -X POST "http://127.0.0.1:2024/threads/$THREAD_ID/runs/stream" \
  -H "Content-Type: application/json" \
  -d '{"assistant_id":"agent","input":{"messages":[{"role":"human","content":"Réponds en une phrase."}]},"stream_mode":"values"}'

curl -fsS "http://127.0.0.1:2024/threads/$THREAD_ID/state" | python -m json.tool
```

Remplacer `agent` par le nom du graphe dans `langgraph.json`.

## Serveur Central Ou Par Service

En développement, un même `langgraph dev` peut exposer plusieurs graphes:

```json
{
  "graphs": {
    "todo_agent": "./src/app/adapters/inbound/langgraph/todo.py:agent",
    "support_agent": "./src/app/adapters/inbound/langgraph/support.py:agent"
  }
}
```

En production, découper par bounded context. Un agent proche du service appelle ses propres ports et
use cases. Un agent central peut orchestrer plusieurs services, mais il appelle leurs APIs, events ou
tools MCP. Il ne lit pas directement leurs repositories ou bases.

## Suite

Lire [agent-persistence](agent-persistence.md), [llm](llm.md), [observability](observability.md), [Validation IA locale](../learning/local-ai-validation.md),
puis le [parcours Todo agent](../tutorials/todo-list/06-agent.md).
