# 5.1 Écrire les tools MCP

Intention: publier les use cases sous forme de tools MCP typés. Chaque tool convertit ses paramètres
en commande ou query applicative.

## Configuration

Vérifier `config/adapters/inbound/fastmcp.yaml`:

```yaml
host: 127.0.0.1
port: 8121
```

## Tool class

Créer le package tools:

```bash
mkdir -p src/todo_list_service/adapters/inbound/fastmcp/tools
touch src/todo_list_service/adapters/inbound/fastmcp/__init__.py
```

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
            due_date: Annotated[date, Field(description="Date d'echeance ISO, ex. 2026-09-01.")],
            description: Annotated[str, Field(description="Description detaillee.")] = "",
            status: Annotated[TodoStatus, Field(description="todo, wip ou done.")] = TodoStatus.TODO,
            completed_at: Annotated[datetime | None, Field(description="Date de realisation si status=done.")] = None,
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

Étape suivante: [brancher le MCP et tester en mémoire](05-mcp-entrypoint-tests.md).
