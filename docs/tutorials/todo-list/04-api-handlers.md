# 4.2 Écrire les handlers HTTP

Intention: adapter une requête HTTP vers un port inbound. Le handler convertit les schémas HTTP en
commandes ou queries applicatives, puis transforme le résultat en enveloppe Arclith.

Il ne connaît ni MongoDB, ni le repository concret.

Créer le package handlers:

```bash
mkdir -p src/todo_list_service/adapters/inbound/fastapi/handlers
touch src/todo_list_service/adapters/inbound/fastapi/handlers/__init__.py
```

Créer `src/todo_list_service/adapters/inbound/fastapi/handlers/todo_handlers.py`:

```python
from __future__ import annotations

from typing import Annotated

from arclith.adapters.inbound.schemas import (
    ApiResponse,
    PaginatedResponse,
    paginated_response,
    success_response,
)
from fastapi import Header, HTTPException, Query, Request, Response
from pydantic import ValidationError

from todo_list_service.adapters.inbound.schemas.todo_schema import (
    TodoCreatedSchema,
    TodoCreateSchema,
    TodoSchema,
)
from todo_list_service.domain.ports.inbound.create_todo import CreateTodoCommand, CreateTodoPort
from todo_list_service.domain.ports.inbound.list_todos import ListTodosPort, ListTodosQuery


class TodoHandlers:
    def __init__(self, create_todo: CreateTodoPort, list_todos: ListTodosPort) -> None:
        self._create_todo = create_todo
        self._list_todos = list_todos

    async def create_todo(
        self,
        payload: TodoCreateSchema,
        response: Response,
        request: Request,
        prefer: Annotated[
            str | None,
            Header(
                description="RFC 7240. Utiliser return=representation pour recevoir la todo complete."
            ),
        ] = None,
    ) -> ApiResponse[TodoCreatedSchema | TodoSchema]:
        try:
            todo = await self._create_todo.execute(
                CreateTodoCommand(
                    title=payload.title,
                    description=payload.description,
                    due_date=payload.due_date,
                    status=payload.status,
                    completed_at=payload.completed_at,
                )
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        collection_url = request.url.path.rstrip("/")
        location = f"{collection_url}/{todo.uuid}"
        links = {"self": location, "collection": collection_url}

        response.headers["Location"] = location
        response.headers["Link"] = f'<{location}>; rel="self", <{collection_url}>; rel="collection"'

        if prefer and "return=representation" in prefer.lower():
            return success_response(TodoSchema.model_validate(todo), links=links)
        return success_response(TodoCreatedSchema(uuid=todo.uuid), links=links)

    async def list_todos(
        self,
        response: Response,
        request: Request,
        page: Annotated[int, Query(ge=1, description="Page a retourner, a partir de 1.")] = 1,
        per_page: Annotated[int, Query(ge=1, le=100, description="Nombre d'elements par page.")] = 20,
    ) -> PaginatedResponse[TodoSchema]:
        result = await self._list_todos.execute(ListTodosQuery(page=page, per_page=per_page))
        todos = [TodoSchema.model_validate(todo) for todo in result.items]
        collection_url = request.url.path.rstrip("/")

        response.headers["X-Total-Count"] = str(result.total)
        response.headers["Link"] = f'<{collection_url}>; rel="self"'
        return paginated_response(
            todos,
            total=result.total,
            page=result.page,
            per_page=result.per_page,
            links={"self": collection_url},
        )
```

Étape suivante: [déclarer le router et brancher FastAPI](04-api-router-main.md).
