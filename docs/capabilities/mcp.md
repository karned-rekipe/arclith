# Capability MCP

Transport MCP exposé via FastMCP.

## Objectif

Le MCP est un adapter inbound. Il expose des tools consommables par un client
MCP ou un assistant, et ces tools appellent les mêmes ports inbound ou use cases
que l'API.

## Adapter

| Adapter | Usage |
|---|---|
| `fastmcp` | serveur MCP créé par `Arclith.fastmcp()` |

## Commande

```bash
arclith-cli add-adapter --capability mcp --adapter fastmcp --yes
```

## Configuration Générée

```yaml
# config/adapters/inbound/fastmcp.yaml
host: 127.0.0.1
port: 8001
```

## Créer Le Serveur

```python
from arclith import Arclith

arclith = Arclith("config")
mcp = arclith.fastmcp("todo-service")
```

## Écrire Un Tool

```python
@mcp.tool
async def create_todo(title: str) -> dict:
    command = CreateTodoCommand(title=title)
    todo = await create_todo_use_case.execute(command)
    return {"uuid": str(todo.uuid), "title": todo.title}
```

Un tool MCP doit rester une façade de transport. Il traduit les arguments du
client, appelle le use case, puis retourne une réponse sérialisable.

## Auth

```python
from fastmcp import Context

require_auth = arclith.auth_dependency(transport="mcp")

@mcp.tool
async def secure_tool(title: str, ctx: Context) -> dict:
    claims = await require_auth(ctx)
    return {"sub": claims.get("sub"), "title": title}
```

L'auth MCP repose sur les headers HTTP disponibles avec les transports HTTP/SSE.
En `stdio`, les headers ne sont pas disponibles: sécuriser alors le canal
d'exécution lui-même.

## Lancer

```python
arclith.run_with_probes(lambda: arclith.run_mcp_http(mcp), transports=["mcp_http"])
```

Le transport HTTP streamable écoute par défaut sur `http://127.0.0.1:8001/mcp/`.

## Instrumentation

Après l'enregistrement des tools, appeler l'instrumentation si les probes sont
actives :

```python
arclith.instrument_mcp(mcp)
```

Les métriques MCP sont ensuite exposées sur le serveur de probes.

## Règles

- Un tool appelle un port inbound ou un use case.
- Un tool ne doit pas accéder au repository concret.
- Les entrées du tool doivent être explicites et typées.
- Les réponses doivent rester sérialisables par le protocole MCP.
- L'auth MCP et l'auth API partagent le même pipeline JWT quand Keycloak est configuré.

## Validation

```bash
MODE=mcp_http uv run python main.py
curl -fsS http://127.0.0.1:9000/info
```

`active_transports` doit contenir `mcp_http`.

Pour tester le protocole :

```bash
uv run python - <<'PY'
import asyncio
from fastmcp import Client

async def main() -> None:
    async with Client("http://127.0.0.1:8001/mcp/") as client:
        tools = await client.list_tools()
        print([tool.name for tool in tools])

asyncio.run(main())
PY
```

## Suite

Lire [auth](auth.md), [probe](probe.md), puis [Deep Dive MCP](../deep-dives/mcp.md).
