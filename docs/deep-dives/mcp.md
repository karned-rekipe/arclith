# Deep Dive MCP

Cette page regroupe les points à approfondir pour FastMCP.

## À Comprendre

- création du serveur avec `Arclith.fastmcp()` ;
- transport streamable HTTP ;
- tools MCP ;
- auth partagée avec l'API ;
- instrumentation des tools.

## Pages Liées

- [mcp/fastmcp](../capabilities/mcp.md)
- [auth/keycloak](../capabilities/auth.md)
- [Tutoriel Todo MCP](../tutorials/todo-list/05-mcp.md)

## Validation Protocolaire

Attendre que le terminal serveur affiche l'URL FastMCP, puis tester le protocole avec un client :

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

## Média

!!! note "Média à produire"
    Capture : client MCP listant les tools.
    Vidéo : ajout d'un tool qui appelle un use case.
