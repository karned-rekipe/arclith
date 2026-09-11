# Quickstart MCP

Créer un projet neuf, ajouter explicitement FastMCP et appeler un tool qui
réutilise le même port applicatif que l'API.

`init` ne crée ni package FastMCP ni dépendance MCP. `add-adapter` crée le
[contrat FastMCP](../deep-dives/adapter-blueprints.md#fastmcp), sans feature
fictive. `expose-usecase` crée ensuite uniquement la feature demandée.

## Prérequis

- Python 3.13 ;
- [`uv`](https://docs.astral.sh/uv/) ;
- `uv tool install arclith-cli` ou l'usage ponctuel de `uvx` ci-dessous.

## Étapes

```bash
uvx --from arclith-cli arclith-cli init todo-mcp --dir .
cd todo-mcp
arclith-cli add-entity Todo
arclith-cli add-usecase CreateTodo --entity Todo
arclith-cli add-adapter --capability repository --adapter memory --yes
arclith-cli add-adapter --capability mcp --adapter fastmcp \
  --param port=8766 --yes
arclith-cli expose-usecase create-todo --via fastmcp --feature todos
uv sync
uv run python -m pytest
MODE=mcp_http uv run python main.py
```

Le serveur streamable HTTP écoute sur `http://127.0.0.1:8766/mcp/`.

## Validation protocolaire

Dans un second terminal :

```bash
uv run python - <<'PY'
import asyncio

from fastmcp import Client


async def main() -> None:
    async with Client("http://127.0.0.1:8766/mcp/") as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == ["create_todo"]
        result = await client.call_tool("create_todo", {"payload": {}})
        print(result.data)


asyncio.run(main())
PY
```

## Résultat

Le tool `create_todo` est présent une seule fois et retourne le DTO contenant
`uuid`, les champs d'audit et `version`. Aucun code FastAPI n'existe tant que
l'adapter API n'a pas été ajouté.

## Suite

Lire [Bus](bus.md), puis [mcp/fastmcp](../capabilities/mcp.md).
