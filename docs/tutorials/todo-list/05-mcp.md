# 5. Exposer un MCP

Objectif: générer la configuration FastMCP avec la CLI, puis exposer les mêmes opérations métier via
des tools MCP.

![Capture interactive FastMCP](assets/05-mcp.svg)

Depuis la racine du projet:

```bash
arclith-cli add-adapter --capability mcp
```

Répondre aux prompts:

```text
① Type d'adapter
   1  fastmcp

  Votre choix (numéro ou nom): 1

③ Paramètres fastmcp
  Host FastMCP (127.0.0.1): 127.0.0.1
  Port FastMCP (8001): 8121

  Confirmer la génération ? [y/n] (y): y
```

La CLI crée:

```text
config/adapters/inbound/fastmcp.yaml
```

## Tools MCP

Le MCP expose le même coeur métier sous forme de tools appelables par un modèle ou un client MCP:

| Fichier | Rôle |
| --- | --- |
| `adapters/inbound/fastmcp/tools/todo_tools.py` | Déclare les tools `create_todo_item` et `list_todo_items`, leurs paramètres typés et leur payload de retour. |
| `adapters/inbound/fastmcp/tools/__init__.py` | Exporte `TodoMCP` pour garder un import stable côté registration. |
| `adapters/inbound/fastmcp/register.py` | Construit les use cases via le container et installe les tools sur l'instance FastMCP. |
| `main.py` | Conserve un seul point d'entrée pour API, MCP HTTP ou les deux transports. |

Un tool MCP n'est pas un raccourci vers la base. Il adapte un appel tool vers un port inbound, comme
l'API adapte une requête HTTP vers le même port.

Créer `src/todo_list_service/adapters/inbound/fastmcp/tools/todo_tools.py`:

```python
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

import fastmcp
from pydantic import Field

from todo_list_service.adapters.inbound.schemas.todo_schema import TodoSchema
from todo_list_service.domain.models.todo import TodoStatus
from todo_list_service.domain.ports.inbound.create_todo import CreateTodoCommand, CreateTodoPort
from todo_list_service.domain.ports.inbound.list_todos import ListTodosPort, ListTodosQuery


class TodoMCP:
    def __init__(
        self,
        create_todo: CreateTodoPort,
        list_todos: ListTodosPort,
        mcp: fastmcp.FastMCP,
    ) -> None:
        self._create_todo = create_todo
        self._list_todos = list_todos
        self._mcp = mcp
        self._register_tools()

    def _register_tools(self) -> None:
        create_todo = self._create_todo
        list_todos = self._list_todos

        @self._mcp.tool
        async def create_todo_item(
            title: Annotated[str, Field(description="Titre court de la todo.")],
            due_date: Annotated[date, Field(description="Date d'échéance ISO, ex. 2026-09-01.")],
            description: Annotated[str, Field(description="Description détaillée.")] = "",
            status: Annotated[TodoStatus, Field(description="todo, wip ou done.")] = TodoStatus.TODO,
            completed_at: Annotated[datetime | None, Field(description="Date de réalisation si status=done.")] = None,
        ) -> dict:
            """Create a todo through the application use case."""
            todo = await create_todo.execute(
                CreateTodoCommand(
                    title=title,
                    description=description,
                    due_date=due_date,
                    status=status,
                    completed_at=completed_at,
                )
            )
            return TodoSchema.model_validate(todo).model_dump(mode="json")

        @self._mcp.tool
        async def list_todo_items() -> list[dict]:
            """List todos through the application use case."""
            result = await list_todos.execute(ListTodosQuery(page=1, per_page=100))
            return [TodoSchema.model_validate(todo).model_dump(mode="json") for todo in result.items]
```

Créer `src/todo_list_service/adapters/inbound/fastmcp/tools/__init__.py`:

```python
from todo_list_service.adapters.inbound.fastmcp.tools.todo_tools import TodoMCP

__all__ = ["TodoMCP"]
```

Créer `src/todo_list_service/adapters/inbound/fastmcp/register.py`:

```python
from __future__ import annotations

import fastmcp

from arclith import Arclith
from todo_list_service.adapters.inbound.fastmcp.tools import TodoMCP
from todo_list_service.infrastructure.containers.todo_container import (
    build_create_todo_use_case,
    build_list_todos_use_case,
)


def register_tools(mcp: fastmcp.FastMCP, arclith: Arclith) -> None:
    create_todo = build_create_todo_use_case(arclith)
    list_todos = build_list_todos_use_case(arclith)
    TodoMCP(create_todo, list_todos, mcp)
```

## Entrypoint API + MCP

Remplacer `main.py` par:

```python
"""Application entrypoint for todo-list-service."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import fastmcp
from arclith import Arclith
from todo_list_service.adapters.inbound.fastapi.register import register_routers
from todo_list_service.adapters.inbound.fastmcp.register import register_tools

_DEFAULT_CONFIG = Path(__file__).parent / "config"
_CONFIG = Path(os.getenv("TODO_LIST_CONFIG_DIR", str(_DEFAULT_CONFIG)))
_VALID_MODES = {"api", "mcp_http", "all"}

MODE = os.getenv("MODE", "api")
if MODE not in _VALID_MODES:
    print(f"MODE invalide: {MODE!r}. Valeurs: {sorted(_VALID_MODES)}", file=sys.stderr)
    sys.exit(1)

arclith = Arclith(_CONFIG)

app = arclith.fastapi()
register_routers(app, arclith)


def build_mcp(config_dir: Path | str | None = None) -> fastmcp.FastMCP:
    current_arclith = arclith if config_dir is None else Arclith(Path(config_dir))
    mcp = current_arclith.fastmcp("Todo MCP")
    register_tools(mcp, current_arclith)
    current_arclith.instrument_mcp(mcp)
    return mcp


def _run_api() -> None:
    arclith.run_api("main:app")


def _run_mcp_http() -> None:
    arclith.run_mcp_http(build_mcp())


if __name__ == "__main__":
    match MODE:
        case "api":
            arclith.run_with_probes(_run_api, transports=["api"])
        case "mcp_http":
            arclith.run_with_probes(_run_mcp_http, transports=["mcp_http"])
        case "all":
            arclith.run_with_probes(_run_api, _run_mcp_http, transports=["api", "mcp_http"])
```

## Tester sans client externe

Créer `tests/test_todo_mcp.py`:

```python
import pytest
from fastmcp import Client

from main import build_mcp


@pytest.mark.asyncio
async def test_mcp_create_and_list_todos() -> None:
    async with Client(build_mcp()) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools} >= {"create_todo_item", "list_todo_items"}

        result = await client.call_tool(
            "create_todo_item",
            {
                "title": "Tester le MCP",
                "description": "Appeler le même use case que l'API",
                "due_date": "2026-09-01",
                "status": "todo",
            },
        )

        assert not result.is_error

        listed = await client.call_tool("list_todo_items", {})
        assert not listed.is_error
```

Quand le runtime final passera à MongoDB, gardez les tests rapides en mémoire avec une fixture qui
copie `config/` dans un dossier temporaire, remplace seulement `repository: mongodb` par
`repository: memory`, puis appelle `build_mcp(memory_config)`. Le POC publié contient cette variante
pour prouver que `create_todo_item` et `list_todo_items` partagent bien le même repository mémoire
dans le même processus de test.

Lancer:

```bash
uv run python -m pytest tests/test_todo_mcp.py
```

Smoke HTTP MCP:

```bash
MODE=mcp_http uv run python main.py
```

Le serveur écoute sur `http://127.0.0.1:8121/mcp`.

## Tester dans LM Studio

LM Studio peut agir comme client MCP depuis l'application. La documentation officielle indique que
le support MCP côté application existe à partir de LM Studio `0.3.17`, et que l'usage MCP via API
demande LM Studio `0.4.0` ou plus récent:

- <https://lmstudio.ai/docs/app/mcp>
- <https://lmstudio.ai/docs/developer/core/mcp>

![Flux LM Studio vers MCP Arclith](assets/05-lmstudio-mcp.svg)

Garder le serveur MCP Arclith lancé:

```bash
MODE=mcp_http uv run python main.py
```

Dans LM Studio:

1. Ouvrir le panneau de droite.
2. Aller dans l'onglet `Program`.
3. Cliquer sur `Install`, puis `Edit mcp.json`.
4. Ajouter le serveur MCP du tutoriel.

Si le fichier est vide, utiliser:

```json
{
  "mcpServers": {
    "todo-list-service": {
      "url": "http://127.0.0.1:8121/mcp"
    }
  }
}
```

Si LM Studio affiche déjà un objet `mcpServers`, ajouter seulement l'entrée
`"todo-list-service"` à l'intérieur.

Tester ensuite dans un chat LM Studio avec une demande courte:

```text
Utilise les tools disponibles pour créer une todo:
titre Tester LM Studio MCP, description Appel MCP depuis LM Studio,
échéance 2026-09-01, statut todo.
```

Le point à vérifier n'est pas la qualité littéraire de la réponse du modèle. Le test est réussi si
LM Studio voit les tools `create_todo_item` et `list_todo_items`, appelle le serveur
`http://127.0.0.1:8121/mcp`, et que les logs du service Arclith montrent l'appel entrant.

Captures à ajouter ou remplacer par une vidéo:

- écran `Program` avec le bouton `Edit mcp.json`;
- contenu `mcp.json` avec `todo-list-service`;
- chat LM Studio montrant l'appel du tool;
- logs du terminal MCP côté Arclith.

Problèmes fréquents:

| Symptôme | Cause probable | Action |
| --- | --- | --- |
| LM Studio ne voit aucun tool | serveur MCP arrêté ou mauvaise URL | vérifier `MODE=mcp_http` et `http://127.0.0.1:8121/mcp` |
| connexion refusée | port différent ou process arrêté | relancer le service MCP |
| le modèle ignore les tools | modèle local trop faible ou tools désactivés | choisir un modèle instruct plus capable et activer les tools |
| appel depuis Docker impossible | `localhost` pointe vers le container | utiliser `host.docker.internal` |

## Voie rapide

```bash
arclith-cli add-adapter \
  --capability mcp \
  --adapter fastmcp \
  --param host=127.0.0.1 \
  --param port=8121 \
  --yes
```

Étape suivante: [ajouter un agent](06-agent.md).
