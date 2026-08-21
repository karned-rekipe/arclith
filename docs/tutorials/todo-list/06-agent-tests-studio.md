# 6.7 Tester l'agent

Intention: verrouiller le comportement agent sans dépendre d'un LLM réel pour les cas déterministes,
puis tester le graphe avec l'API locale LangGraph. Studio reste utile quand internet est disponible.

## Tests unitaires

Créer `tests/test_todo_agent.py`:

```python
from datetime import date, timedelta

import pytest
from langgraph.graph import END

from todo_list_service.adapters.inbound.langgraph import agent as agent_module
from todo_list_service.adapters.inbound.langgraph.collection import apply_default_fields, apply_pending_answer, missing_fields
from todo_list_service.adapters.inbound.langgraph.intent import detect_high_confidence_action
from todo_list_service.adapters.inbound.langgraph.nodes import route_intent as route_intent_node
from todo_list_service.adapters.inbound.langgraph.routing import route_after_collection, route_after_intent
from todo_list_service.application.intent_interpreters.todo_action import TodoAction, TodoActionDecision
from todo_list_service.application.intent_interpreters.todo_conversation import TodoDraft
from todo_list_service.domain.models.todo import Todo, TodoStatus
from todo_list_service.domain.ports.inbound.create_todo import CreateTodoCommand
from todo_list_service.domain.ports.inbound.list_todos import ListTodosQuery, ListTodosResult


class FakeActionInterpreter:
    def __init__(self, action: TodoAction) -> None:
        self._action = action
        self.prompts: list[str] = []

    async def classify(self, prompt: str) -> TodoActionDecision:
        self.prompts.append(prompt)
        return TodoActionDecision(action=self._action)


class FakeIntentInterpreter:
    async def extract(self, prompt: str, current: TodoDraft) -> TodoDraft:
        return TodoDraft(description="Ecrire la documentation", status=TodoStatus.TODO)


class ExplodingIntentInterpreter:
    async def extract(self, prompt: str, current: TodoDraft) -> TodoDraft:
        raise AssertionError("Le LLM ne doit pas etre appele pour ce cas localement evident.")


class FakeCreateTodoUseCase:
    def __init__(self) -> None:
        self.commands: list[CreateTodoCommand] = []

    async def execute(self, command: CreateTodoCommand) -> Todo:
        self.commands.append(command)
        return Todo(
            title=command.title,
            description=command.description,
            due_date=command.due_date,
            status=command.status,
            completed_at=command.completed_at,
        )


class FakeListTodosUseCase:
    def __init__(self) -> None:
        self.queries: list[ListTodosQuery] = []

    async def execute(self, query: ListTodosQuery) -> ListTodosResult:
        self.queries.append(query)
        todo = Todo(
            title="Tester le listing",
            description="Prouver le coeur partage",
            due_date=date(2026, 9, 1),
            status=TodoStatus.TODO,
        )
        return ListTodosResult(items=[todo], total=1, page=query.page, per_page=query.per_page)


@pytest.mark.asyncio
async def test_pending_title_answer_updates_title_instead_of_looping(monkeypatch: pytest.MonkeyPatch) -> None:
    create_todo = FakeCreateTodoUseCase()
    monkeypatch.setattr(agent_module, "_action_interpreter", lambda: FakeActionInterpreter(TodoAction.CREATE_TODO))
    monkeypatch.setattr(agent_module, "_intent_interpreter", lambda: FakeIntentInterpreter())
    monkeypatch.setattr(agent_module, "_create_todo_use_case", lambda: create_todo)

    first = await agent_module.run_agent(
        {"messages": [{"role": "user", "content": "Ajoute une todo pour ecrire la doc"}]}
    )

    assert first["draft"]["title"] == "ecrire la doc"
    assert first["pending_field"] == "due_date"
    assert first["answer"] == "Quelle est la date d'echeance ?"

    second = await agent_module.run_agent(
        {
            **first,
            "messages": [*first["messages"], {"role": "user", "content": "2026-09-01"}],
        }
    )

    assert create_todo.commands[0].title == "ecrire la doc"
    assert create_todo.commands[0].due_date == date(2026, 9, 1)
    assert create_todo.commands[0].description == "Ecrire la documentation"
    assert create_todo.commands[0].status == TodoStatus.TODO
    assert second["pending_field"] is None


@pytest.mark.asyncio
async def test_agent_creates_simple_todo_from_obligation_and_relative_date(monkeypatch: pytest.MonkeyPatch) -> None:
    create_todo = FakeCreateTodoUseCase()
    monkeypatch.setattr(agent_module, "_create_todo_use_case", lambda: create_todo)
    monkeypatch.setattr(agent_module, "_intent_interpreter", lambda: ExplodingIntentInterpreter())

    result = await agent_module.run_agent(
        {"messages": [{"role": "user", "content": "Je dois acheter des bananes demain"}]}
    )

    assert len(create_todo.commands) == 1
    assert create_todo.commands[0].title == "acheter des bananes"
    assert create_todo.commands[0].due_date == date.today() + timedelta(days=1)
    assert create_todo.commands[0].description == ""
    assert create_todo.commands[0].status == TodoStatus.TODO
    assert result["pending_field"] is None


@pytest.mark.asyncio
async def test_agent_cancels_pending_todo_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    create_todo = FakeCreateTodoUseCase()
    monkeypatch.setattr(agent_module, "_create_todo_use_case", lambda: create_todo)

    result = await agent_module.run_agent(
        {
            "messages": [{"role": "user", "content": "Annule"}],
            "draft": {"title": "acheter des bananes"},
            "pending_field": "due_date",
        }
    )

    assert create_todo.commands == []
    assert result["action"] == TodoAction.CANCEL_TODO_CREATION
    assert result["draft"] == {}
    assert result["pending_field"] is None
    assert result["answer"] == "Creation de todo annulee."


@pytest.mark.asyncio
async def test_agent_lists_todos_through_list_use_case(monkeypatch: pytest.MonkeyPatch) -> None:
    list_todos = FakeListTodosUseCase()
    monkeypatch.setattr(agent_module, "_action_interpreter", lambda: FakeActionInterpreter(TodoAction.LIST_TODOS))
    monkeypatch.setattr(agent_module, "_list_todos_use_case", lambda: list_todos)

    result = await agent_module.run_agent(
        {"messages": [{"role": "user", "content": "Liste mes todos"}]}
    )

    assert list_todos.queries == [ListTodosQuery(page=1, per_page=20)]
    assert result["action"] == TodoAction.LIST_TODOS
    assert result["todos"][0]["title"] == "Tester le listing"
    assert "Tester le listing" in result["answer"]


@pytest.mark.asyncio
async def test_agent_treats_what_should_i_do_today_as_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    create_todo = FakeCreateTodoUseCase()
    list_todos = FakeListTodosUseCase()
    monkeypatch.setattr(agent_module, "_create_todo_use_case", lambda: create_todo)
    monkeypatch.setattr(agent_module, "_list_todos_use_case", lambda: list_todos)

    result = await agent_module.run_agent(
        {"messages": [{"role": "user", "content": "Qu'est ce que je dois faire aujourd'hui ?"}]}
    )

    assert create_todo.commands == []
    assert list_todos.queries == [ListTodosQuery(page=1, per_page=20)]
    assert result["action"] == TodoAction.LIST_TODOS


@pytest.mark.asyncio
async def test_route_intent_uses_structured_action_interpreter() -> None:
    interpreter = FakeActionInterpreter(TodoAction.LIST_TODOS)

    result = await route_intent_node(
        {"messages": [{"role": "user", "content": "status please"}]},
        lambda: interpreter,
    )

    assert result["action"] == TodoAction.LIST_TODOS
    assert interpreter.prompts == ["status please"]


@pytest.mark.asyncio
async def test_route_intent_uses_local_fast_path_before_llm() -> None:
    interpreter = FakeActionInterpreter(TodoAction.UNKNOWN)

    result = await route_intent_node(
        {"messages": [{"role": "user", "content": "Liste mes todos"}]},
        lambda: interpreter,
    )

    assert result["action"] == TodoAction.LIST_TODOS
    assert interpreter.prompts == []


@pytest.mark.asyncio
async def test_route_intent_uses_llm_for_ambiguous_todo_domain_prompt() -> None:
    interpreter = FakeActionInterpreter(TodoAction.CREATE_TODO)

    result = await route_intent_node(
        {"messages": [{"role": "user", "content": "ma todo pour appeler Paul"}]},
        lambda: interpreter,
    )

    assert result["action"] == TodoAction.CREATE_TODO
    assert interpreter.prompts == ["ma todo pour appeler Paul"]


def test_detect_high_confidence_action_does_not_match_substrings() -> None:
    result = detect_high_confidence_action("Peux-tu revoir mes notes ?", {})

    assert result == TodoAction.UNKNOWN


def test_detect_high_confidence_action_keeps_vague_todo_prompt_for_llm() -> None:
    result = detect_high_confidence_action("mes taches importantes", {})

    assert result == TodoAction.UNKNOWN


def test_detect_high_confidence_action_routes_should_do_question_to_listing() -> None:
    result = detect_high_confidence_action("Qu'est ce que je dois faire aujourd'hui ?", {})

    assert result == TodoAction.LIST_TODOS


def test_apply_pending_answer_parses_status_in_collection_boundary() -> None:
    updated, handled = apply_pending_answer("termine", TodoDraft(), "status")

    assert handled
    assert updated.status == TodoStatus.DONE


def test_missing_fields_returns_empty_list_for_complete_todo_draft() -> None:
    draft = TodoDraft(
        title="Ecrire les tests",
        description="Couvrir les helpers LangGraph",
        due_date=date(2026, 9, 1),
        status=TodoStatus.TODO,
    )

    assert missing_fields(draft) == []


def test_missing_fields_does_not_require_description_or_status() -> None:
    draft = TodoDraft(
        title="acheter des bananes",
        due_date=date(2026, 9, 1),
    )

    assert missing_fields(draft) == []


def test_apply_default_fields_sets_description_and_todo_status() -> None:
    draft = apply_default_fields(TodoDraft(title="acheter des bananes", due_date=date(2026, 9, 1)))

    assert draft.description == ""
    assert draft.status == TodoStatus.TODO


def test_route_after_collection_waits_when_a_field_is_pending() -> None:
    assert route_after_collection({"pending_field": "title"}) == END
    assert route_after_collection({"pending_field": None}) == "create_todo"


def test_route_after_intent_can_cancel_creation() -> None:
    assert route_after_intent({"action": TodoAction.CANCEL_TODO_CREATION}) == "cancel_todo_creation"
```

Lancer les tests unitaires agent:

```bash
uv run python -m pytest tests/test_todo_agent.py
```

Ces tests couvrent les comportements importants:

- une réponse à `pending_field` met à jour le bon champ;
- `Je dois acheter des bananes demain` extrait le titre et la date sans LLM;
- une annulation vide le brouillon et n'appelle pas `CreateTodoPort`;
- `Liste mes todos` appelle `ListTodosPort`;
- `Qu'est ce que je dois faire aujourd'hui ?` liste les todos au lieu de créer une tâche;
- les prompts ambigus passent par `TodoActionInterpreter`.

## LangGraph API Locale

Lancer l'Agent Server local:

```bash
export LANGSMITH_TRACING=false
export LANGGRAPH_CLI_NO_ANALYTICS=1
uv run langgraph dev --no-browser --allow-blocking --port 2024
```

Le terminal affiche une API locale et, si internet est disponible, une URL Studio:

```text
http://127.0.0.1:2024
http://127.0.0.1:2024/docs
https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

En offline, utiliser l'API locale. Tester un run stateless:

```bash
curl -N -X POST "http://127.0.0.1:2024/runs/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "todo_agent",
    "input": {
      "messages": [
        {"role": "human", "content": "Je dois acheter des bananes demain"}
      ]
    },
    "stream_mode": "values"
  }'
```

Créer ensuite un thread durable pour relire l'état:

```bash
THREAD_ID=$(curl -fsS -X POST "http://127.0.0.1:2024/threads" \
  -H "Content-Type: application/json" \
  -d '{}' | python -c 'import json,sys; print(json.load(sys.stdin)["thread_id"])')

curl -N -X POST "http://127.0.0.1:2024/threads/$THREAD_ID/runs/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "todo_agent",
    "input": {
      "messages": [
        {"role": "human", "content": "Quelles sont mes taches en cours ?"}
      ]
    },
    "stream_mode": "values"
  }'

curl -fsS "http://127.0.0.1:2024/threads/$THREAD_ID/state" | python -m json.tool
curl -fsS "http://127.0.0.1:2024/threads/$THREAD_ID/runs" | python -m json.tool
```

## LangGraph Studio

Si Studio est accessible, utiliser les mêmes payloads depuis l'interface.

Créer une todo simple:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "Je dois acheter des bananes demain"
    }
  ]
}
```

Résultat attendu:

```text
Todo creee: acheter des bananes (<uuid>).
```

Lister les todos:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "Qu'est ce que je dois faire aujourd'hui ?"
    }
  ]
}
```

Résultat attendu: une réponse de listing.

Tester une création incomplète:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "Ajoute une todo pour écrire la doc"
    }
  ]
}
```

L'agent doit demander la date d'échéance, car `description` et `status` ont des défauts. Répondre
dans le même thread LangGraph pour conserver `draft` et `pending_field`.

Tester une annulation dans un état de création:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "Annule"
    }
  ],
  "draft": {
    "title": "acheter des bananes"
  },
  "pending_field": "due_date"
}
```

Résultat attendu:

```text
Creation de todo annulee.
```

Pour plus de commandes offline, lire
[Validation IA locale et hors ligne](../../learning/local-ai-validation.md).

Étape suivante: [annexes locales](07-local-services.md).
