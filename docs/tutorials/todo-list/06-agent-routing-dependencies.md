# 6.5 Formatter, router et injecter les dépendances

Intention: isoler les fonctions techniques du graphe. Les formatters ne font que présenter les
résultats, le routing ne fait que choisir la prochaine étape, et les dépendances ne font que câbler
Arclith, le LLM et les ports.

## Formatters

Modifier `src/todo_list_service/adapters/inbound/langgraph/formatters.py`:

```python
from typing import Any

from todo_list_service.domain.models.todo import Todo
from todo_list_service.domain.ports.inbound.list_todos import ListTodosResult


def todo_to_agent_item(todo: Todo) -> dict[str, Any]:
    return todo.model_dump(mode="json")


def format_todos(result: ListTodosResult) -> str:
    if result.total == 0:
        return "Aucune todo pour le moment."

    lines = [f"Voici {len(result.items)} todo(s) sur {result.total}:"]
    lines.extend(format_todo_line(todo) for todo in result.items)
    return "\n".join(lines)


def format_todo_line(todo: Todo) -> str:
    description = f" - {todo.description}" if todo.description else ""
    return (
        f"- {todo.title} [{todo.status.value}] "
        f"pour le {todo.due_date.isoformat()}{description} ({todo.uuid})"
    )
```

## Routing

Modifier `src/todo_list_service/adapters/inbound/langgraph/routing.py`:

```python
from langgraph.graph import END

from todo_list_service.adapters.inbound.langgraph.state import AgentState
from todo_list_service.application.intent_interpreters.todo_action import TodoAction


def route_after_intent(state: AgentState) -> str:
    action = state.get("action", TodoAction.UNKNOWN)
    if action == TodoAction.LIST_TODOS:
        return "list_todos"
    if action == TodoAction.CANCEL_TODO_CREATION:
        return "cancel_todo_creation"
    if action == TodoAction.CREATE_TODO:
        return "collect_todo_details"
    return "answer_unknown"


def route_after_collection(state: AgentState) -> str:
    if state.get("pending_field") is not None:
        return END
    return "create_todo"
```

## Dépendances

Modifier `src/todo_list_service/adapters/inbound/langgraph/dependencies.py`:

```python
from functools import lru_cache

from arclith import Arclith
from arclith.adapters.outbound.pydantic_ai.llm import PydanticAILLMAdapter
from arclith.domain.ports.outbound.llm import LLMPort

from todo_list_service.application.intent_interpreters.todo_action import TodoActionInterpreter
from todo_list_service.application.intent_interpreters.todo_conversation import TodoConversationInterpreter
from todo_list_service.domain.ports.inbound.create_todo import CreateTodoPort
from todo_list_service.domain.ports.inbound.list_todos import ListTodosPort
from todo_list_service.infrastructure.containers.todo_container import (
    build_create_todo_use_case,
    build_list_todos_use_case,
)

arclith = Arclith("config")


@lru_cache(maxsize=1)
def create_todo_use_case() -> CreateTodoPort:
    return build_create_todo_use_case(arclith)


@lru_cache(maxsize=1)
def list_todos_use_case() -> ListTodosPort:
    return build_list_todos_use_case(arclith)


@lru_cache(maxsize=1)
def llm_adapter() -> LLMPort:
    lm_settings = arclith.config.adapters.lm
    if lm_settings is None:
        raise RuntimeError("config/adapters/outbound/lm.yaml est requis pour l'agent.")
    return PydanticAILLMAdapter(lm_settings)


@lru_cache(maxsize=1)
def action_interpreter() -> TodoActionInterpreter:
    return TodoActionInterpreter(llm_adapter())


@lru_cache(maxsize=1)
def intent_interpreter() -> TodoConversationInterpreter:
    return TodoConversationInterpreter(llm_adapter())
```

Étape suivante: [écrire les noeuds et assembler le graphe](06-agent-nodes-graph.md).
