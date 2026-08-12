# Modes Runtime

Arclith sépare le code métier des modes de lancement.

## Modes Courants

| Mode | Usage |
|---|---|
| `api` | API FastAPI |
| `mcp_http` | serveur MCP streamable HTTP |
| `mcp_sse` | serveur MCP SSE |
| `bus` | worker command bus |
| `agent` | agent LangGraph |
| `all` | développement local multi-transport |

## Exemple

```bash
MODE=api uv run python main.py
MODE=mcp_http uv run python main.py
```

`bus` et `agent` nécessitent un câblage projet : `CommandDispatcher` pour le bus, `langgraph.json`
ou `ARCLITH_AGENT_COMMAND` pour l'agent.

## Validation

Les probes donnent l'état runtime :

```bash
curl -fsS http://127.0.0.1:9000/info
```

## Suite

Lire [Docker](../runtime-docker.md) pour lancer les mêmes modes en conteneur.
