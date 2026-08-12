# Capability Agent

Runtime agent basé sur LangGraph.

## Objectif

Un agent est un adapter inbound. Il reçoit une intention utilisateur, maintient
un état de graphe, puis appelle les ports inbound ou use cases Arclith.

## Adapter

| Adapter | Usage |
|---|---|
| `langgraph` | entrypoint LangGraph Studio |

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


agent = arclith.langgraph(AgentState, register_agent, name="agent")
```

Le template généré est volontairement minimal. Le projet remplace ensuite
`AgentState`, les nodes et les edges par son propre parcours.

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

## Suite

Lire [llm](llm.md), [observability](observability.md), puis le [parcours Todo agent](../tutorials/todo-list/06-agent.md).
