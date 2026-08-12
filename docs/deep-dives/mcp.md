# Deep Dive MCP

Cette page explique comment exposer un service Arclith via MCP.

## Position

Le MCP est un adapter inbound. Il expose des tools à un client MCP, puis ces
tools appellent les mêmes use cases que l'API.

```text
MCP client
  -> tool FastMCP
  -> arguments typés
  -> use case
  -> réponse sérialisable
```

Le tool n'est pas un deuxième coeur métier. Il est une façade de protocole.

## Création Du Serveur

```python
from arclith import Arclith

arclith = Arclith("config")
mcp = arclith.fastmcp("todo-service")
```

La configuration `config/adapters/inbound/fastmcp.yaml` définit le host et le
port du transport HTTP streamable.

## Tool Propre

Un tool propre reçoit des arguments explicites, construit une commande métier,
appelle le use case, puis retourne un dictionnaire ou un type sérialisable.

```python
@mcp.tool
async def create_todo(title: str, due_date: str) -> dict:
    command = CreateTodoCommand(title=title, due_date=due_date)
    todo = await create_todo_use_case.execute(command)
    return {"uuid": str(todo.uuid), "title": todo.title}
```

Éviter les tools qui font plusieurs intentions à la fois. Un tool doit avoir une
responsabilité claire.

## Auth

```python
from fastmcp import Context

require_auth = arclith.auth_dependency(transport="mcp")

@mcp.tool
async def secure_tool(title: str, ctx: Context) -> dict:
    claims = await require_auth(ctx)
    return {"sub": claims.get("sub"), "title": title}
```

L'auth MCP utilise les headers HTTP disponibles avec le transport HTTP/SSE. En
transport `stdio`, sécuriser le processus qui lance le serveur plutôt que de
compter sur des headers absents.

## Multitenant

Le pipeline tenant MCP suit le même principe que l'API: JWT, licence éventuelle,
claim tenant, résolution des coordonnées, puis contexte de requête.

Utiliser la même convention de claim que l'API pour éviter deux modèles de
sécurité différents.

## Instrumentation

Appeler l'instrumentation après l'enregistrement des tools:

```python
arclith.instrument_mcp(mcp)
```

L'instrumentation enveloppe les fonctions FastMCP et alimente les métriques
exposées par le serveur de probes.

## Lancement

```python
arclith.run_with_probes(
    lambda: arclith.run_mcp_http(mcp),
    transports=["mcp_http"],
)
```

Le transport HTTP streamable écoute par défaut sur
`http://127.0.0.1:8001/mcp/`.

## Erreurs Fréquentes

| Erreur | Correction |
|---|---|
| tool qui accède au repository | appeler un use case |
| retour non sérialisable | convertir en dict, liste ou type simple |
| auth testée en `stdio` comme en HTTP | distinguer le modèle de transport |
| instrumentation appelée trop tôt | appeler `instrument_mcp` après les tools |
| client sur mauvais chemin | utiliser `/mcp/` avec le slash final |

## Pages Liées

- [Capability MCP](../capabilities/mcp.md)
- [Capability Auth](../capabilities/auth.md)
- [Capability Probe](../capabilities/probe.md)
- [Tutoriel Todo MCP](../tutorials/todo-list/05-mcp.md)

## Validation Protocolaire

Attendre que le terminal serveur affiche l'URL FastMCP, puis tester le protocole
avec un client:

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

Si la connexion échoue, vérifier d'abord qu'aucun autre service n'écoute sur `8001`.

Vérifier aussi les probes:

```bash
curl -fsS http://127.0.0.1:9000/info
```

`active_transports` doit contenir `mcp_http`.

## Média

!!! note "Média à produire"
    Capture : client MCP listant les tools.
    Vidéo : ajout d'un tool qui appelle un use case.
