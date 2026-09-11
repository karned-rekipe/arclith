# 5.2 Entrypoint et tests MCP

`main.build_mcp()` crée le serveur via `Arclith.fastmcp()`, construit une seule
fois les use cases dans `infrastructure/use_cases_generated.py`, puis appelle
`fastmcp/register.py`. L'agrégateur `bindings_generated.py` injecte ensuite le
port dans la feature `todos`.

Lancer le serveur HTTP MCP :

```bash
uv sync
MODE=mcp_http uv run python main.py
```

Le test de contrat généré ne nécessite pas de serveur. Pour contrôler également
l'enregistrement réel du tool, FastMCP fournit un client en processus :

```python
import pytest
from fastmcp import Client

from main import build_mcp


@pytest.mark.asyncio
async def test_create_todo_tool_is_registered_once() -> None:
    async with Client(build_mcp()) as client:
        tools = await client.list_tools()
        result = await client.call_tool("create_todo", {"payload": {}})

    assert [tool.name for tool in tools] == ["create_todo"]
    assert result.structured_content is not None
    assert result.structured_content["version"] == 1
```

Le projet MCP ne doit contenir aucun dossier FastAPI sauf si
`add-adapter --capability api --adapter fastapi` a été exécuté séparément.

Étape suivante : [connecter LM Studio](05-mcp-lm-studio.md).
