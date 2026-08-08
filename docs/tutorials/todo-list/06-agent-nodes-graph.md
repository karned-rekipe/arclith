# 6.6 Écrire les noeuds et assembler le graphe

Intention: écrire les unités exécutées par LangGraph, puis les brancher dans un graphe explicite.
Les noeuds appellent des factories injectées pour rester testables.

## Noeuds

Modifier `src/todo_list_service/adapters/inbound/langgraph/nodes.py`:

```python
from collections.abc import Callable

from pydantic import ValidationError

from todo_list_service.adapters.inbound.langgraph.collection import (
    apply_pending_answer,
    apply_default_fields,
    enrich_draft_from_prompt,
    missing_fields,
    question_for,
)
from todo_list_service.adapters.inbound.langgraph.formatters import format_todos, todo_to_agent_item
from todo_list_service.adapters.inbound.langgraph.intent import detect_high_confidence_action
from todo_list_service.adapters.inbound.langgraph.state import (
    AgentState,
    assistant_message,
    draft_from_state,
    last_user_message,
)
from todo_list_service.application.intent_interpreters.todo_action import TodoAction, TodoActionInterpreter
from todo_list_service.application.intent_interpreters.todo_conversation import TodoConversationInterpreter
from todo_list_service.domain.models.todo import TodoStatus
from todo_list_service.domain.ports.inbound.create_todo import CreateTodoCommand, CreateTodoPort
from todo_list_service.domain.ports.inbound.list_todos import ListTodosPort, ListTodosQuery

type CreateTodoUseCaseFactory = Callable[[], CreateTodoPort]
type ListTodosUseCaseFactory = Callable[[], ListTodosPort]
type ActionInterpreterFactory = Callable[[], TodoActionInterpreter]
type IntentInterpreterFactory = Callable[[], TodoConversationInterpreter]


async def route_intent(state: AgentState, get_action_interpreter: ActionInterpreterFactory) -> AgentState:
    prompt = last_user_message(state)
    local_action = detect_high_confidence_action(prompt, state)
    if local_action != TodoAction.UNKNOWN:
        return {"action": local_action}
    if not prompt.strip():
        return {"action": TodoAction.UNKNOWN}

    decision = await get_action_interpreter().classify(prompt)
    return {"action": decision.action}


async def collect_todo_details(state: AgentState, get_interpreter: IntentInterpreterFactory) -> AgentState:
    prompt = last_user_message(state)
    current = draft_from_state(state)
    pending_field = state.get("pending_field")

    if prompt:
        current, handled_pending = apply_pending_answer(prompt, current, pending_field)
        if not handled_pending:
            current = enrich_draft_from_prompt(prompt, current)
            missing_before_llm = missing_fields(apply_default_fields(current))
            if not missing_before_llm:
                return {
                    "draft": apply_default_fields(current).model_dump(mode="json", exclude_none=True),
                    "pending_field": None,
                }
            if pending_field:
                prompt = f"Le message utilisateur repond au champ {pending_field!r}: {prompt}"
            extracted = await get_interpreter().extract(prompt, current)
            current = current.model_copy(update=extracted.model_dump(exclude_none=True))
            current = enrich_draft_from_prompt(prompt, current)

    current = apply_default_fields(current)
    missing = missing_fields(current)
    if missing:
        pending_field = missing[0]
        answer = question_for(pending_field)
        return {
            "draft": current.model_dump(mode="json", exclude_none=True),
            "pending_field": pending_field,
            "answer": answer,
            "messages": [assistant_message(answer)],
        }

    return {
        "draft": current.model_dump(mode="json", exclude_none=True),
        "pending_field": None,
    }


async def cancel_todo_creation(state: AgentState) -> AgentState:
    answer = "Creation de todo annulee."
    return {
        "action": TodoAction.CANCEL_TODO_CREATION,
        "draft": {},
        "pending_field": None,
        "answer": answer,
        "messages": [assistant_message(answer)],
    }


async def create_todo(state: AgentState, get_create_use_case: CreateTodoUseCaseFactory) -> AgentState:
    current = draft_from_state(state)

    try:
        todo = await get_create_use_case().execute(
            CreateTodoCommand(
                title=current.title or "",
                description=current.description or "",
                due_date=current.due_date,
                status=current.status or TodoStatus.TODO,
                completed_at=current.completed_at,
            )
        )
    except (ValidationError, ValueError) as exc:
        answer = f"Je ne peux pas creer la todo: {exc}"
        return {
            "answer": answer,
            "messages": [assistant_message(answer)],
        }

    answer = f"Todo creee: {todo.title} ({todo.uuid})."
    return {
        "draft": {},
        "pending_field": None,
        "answer": answer,
        "messages": [assistant_message(answer)],
    }


async def list_todos(state: AgentState, get_list_use_case: ListTodosUseCaseFactory) -> AgentState:
    result = await get_list_use_case().execute(ListTodosQuery(page=1, per_page=20))
    answer = format_todos(result)
    return {
        "todos": [todo_to_agent_item(todo) for todo in result.items],
        "answer": answer,
        "messages": [assistant_message(answer)],
    }


async def answer_unknown(state: AgentState) -> AgentState:
    answer = "Je peux creer une todo ou lister les todos. Que veux-tu faire ?"
    return {
        "action": TodoAction.UNKNOWN,
        "answer": answer,
        "messages": [assistant_message(answer)],
    }
```

## Graphe

Modifier `src/todo_list_service/adapters/inbound/langgraph/agent.py`:

```python
from typing import Any

from arclith import Arclith
from langgraph.graph import END, START

from todo_list_service.adapters.inbound.langgraph.dependencies import (
    action_interpreter,
    arclith,
    create_todo_use_case,
    intent_interpreter,
    list_todos_use_case,
)
from todo_list_service.adapters.inbound.langgraph.nodes import (
    answer_unknown as answer_unknown_node,
    cancel_todo_creation as cancel_todo_creation_node,
    collect_todo_details as collect_todo_details_node,
    create_todo as create_todo_node,
    list_todos as list_todos_node,
    route_intent as route_intent_node,
)
from todo_list_service.adapters.inbound.langgraph.routing import (
    route_after_collection,
    route_after_intent,
)
from todo_list_service.adapters.inbound.langgraph.state import AgentState
from todo_list_service.application.intent_interpreters.todo_action import TodoActionInterpreter
from todo_list_service.application.intent_interpreters.todo_conversation import TodoConversationInterpreter
from todo_list_service.domain.ports.inbound.create_todo import CreateTodoPort
from todo_list_service.domain.ports.inbound.list_todos import ListTodosPort


def _create_todo_use_case() -> CreateTodoPort:
    return create_todo_use_case()


def _list_todos_use_case() -> ListTodosPort:
    return list_todos_use_case()


def _action_interpreter() -> TodoActionInterpreter:
    return action_interpreter()


def _intent_interpreter() -> TodoConversationInterpreter:
    return intent_interpreter()


def _route_after_intent(state: AgentState) -> str:
    return route_after_intent(state)


def _route_after_collection(state: AgentState) -> str:
    return route_after_collection(state)


async def route_intent(state: AgentState) -> AgentState:
    return await route_intent_node(state, _action_interpreter)


async def collect_todo_details(state: AgentState) -> AgentState:
    return await collect_todo_details_node(state, _intent_interpreter)


async def create_todo(state: AgentState) -> AgentState:
    return await create_todo_node(state, _create_todo_use_case)


async def list_todos(state: AgentState) -> AgentState:
    return await list_todos_node(state, _list_todos_use_case)


async def answer_unknown(state: AgentState) -> AgentState:
    return await answer_unknown_node(state)


async def cancel_todo_creation(state: AgentState) -> AgentState:
    return await cancel_todo_creation_node(state)


async def run_agent(state: AgentState) -> AgentState:
    return await agent.ainvoke(state)


def register_agent(builder: Any, app: Arclith) -> None:
    builder.add_node("route_intent", route_intent)
    builder.add_node("collect_todo_details", collect_todo_details)
    builder.add_node("create_todo", create_todo)
    builder.add_node("list_todos", list_todos)
    builder.add_node("answer_unknown", answer_unknown)
    builder.add_node("cancel_todo_creation", cancel_todo_creation)

    builder.add_edge(START, "route_intent")
    builder.add_conditional_edges(
        "route_intent",
        _route_after_intent,
        ["collect_todo_details", "list_todos", "cancel_todo_creation", "answer_unknown"],
    )
    builder.add_conditional_edges(
        "collect_todo_details",
        _route_after_collection,
        ["create_todo", END],
    )
    builder.add_edge("create_todo", END)
    builder.add_edge("list_todos", END)
    builder.add_edge("answer_unknown", END)
    builder.add_edge("cancel_todo_creation", END)


agent = arclith.langgraph(AgentState, register_agent, name="todo_agent")
```

Étape suivante: [tester l'agent](06-agent-tests-studio.md).
