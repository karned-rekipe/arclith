# Capability Agent

Runtime agent basé sur LangGraph.

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

## Règle

Un nœud LangGraph appelle un use case ou un port inbound. Il ne contourne pas l'application.

## Validation

```bash
uv run langgraph dev
```

## Suite

Lire [Quickstart Agent](../quickstarts/agent.md).
