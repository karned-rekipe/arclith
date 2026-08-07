# 6. Ajouter un agent

Objectif: créer un agent LangGraph qui pose les questions manquantes, puis appelle `CreateTodoPort`
avec les mêmes données que l'API et le MCP.

![Capture interactive agent](assets/06-agent.svg)

L'agent a deux responsabilités:

- transformer la conversation en `TodoDraft`;
- demander les champs manquants avant d'enregistrer.

Il ne connaît pas la persistance. Il appelle le use case applicatif.

## Installer les dépendances agent

```bash
uv add "arclith[langgraph]"
```

## Créer l'interpréteur d'intention

Depuis la racine du projet:

```bash
arclith-cli add-intent-interpreter
```

Répondre:

```text
Interpréteur d'intention (ex : IngredientIntent, todo_intent)
  Nom de l'interpréteur: TodoConversation
```

Remplacer `src/todo_list_service/application/intent_interpreters/todo_conversation.py` par:

```python
from __future__ import annotations

from datetime import date, datetime

from arclith.domain.ports.outbound.llm import LLMPort
from pydantic import BaseModel, Field

from todo_list_service.domain.models.todo import TodoStatus


class TodoDraft(BaseModel):
    title: str | None = Field(default=None)
    description: str | None = Field(default=None)
    due_date: date | None = Field(default=None)
    status: TodoStatus | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)


class TodoConversationInterpreter:
    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def extract(self, prompt: str, current: TodoDraft) -> TodoDraft:
        return await self._llm.complete_structured(
            prompt,
            output_type=TodoDraft,
            instructions=(
                "Tu extrais les champs d'une todo à partir d'une conversation en français. "
                "Quand la demande est de type 'ajoute une todo pour X' ou 'crée une todo pour X', "
                "X est le titre de la todo, sauf si l'utilisateur dit explicitement que c'est une description. "
                "Retourne uniquement les champs explicitement présents ou clairement déduits. "
                "Ne fabrique pas de titre, de description ou de date. "
                f"Draft actuel: {current.model_dump_json(exclude_none=True)}"
            ),
        )
```

## Configurer LM Studio

Démarrer LM Studio Local Server sur `http://127.0.0.1:1234/v1`, puis vérifier les modèles:

```bash
curl -fsS http://127.0.0.1:1234/v1/models
```

Lancer le wizard LLM:

```bash
arclith-cli add-adapter --capability llm
```

Répondre:

```text
① Type d'adapter
   1  lmstudio
   2  openai
   3  anthropic

  Votre choix (numéro ou nom): 1

③ Paramètres lmstudio
  Model ID LM Studio: <model-id-lm-studio>
  Endpoint OpenAI-compatible LM Studio (http://127.0.0.1:1234/v1):
  API key LM Studio (lm-studio):

  Confirmer la génération ? [y/n] (y): y
```

La CLI crée:

```text
config/adapters/outbound/lm.yaml
```

## Configurer LangSmith

LangSmith est optionnel pour exécuter localement, mais utile pour inspecter les runs.

```bash
arclith-cli add-adapter --capability observability
```

Répondre:

```text
① Type d'adapter
   1  langsmith
   2  opentelemetry

  Votre choix (numéro ou nom): 1
  Activer LANGSMITH_TRACING [y/n] (y): y
  Projet LangSmith (todo-list-service): todo-list-service-dev
  Endpoint LangSmith (https://api.smith.langchain.com):
  LANGSMITH_API_KEY:
  Activer langsmith maintenant ? [y/n] (y): y
  Confirmer la génération ? [y/n] (y): y
```

La clé reste dans `.env`, jamais dans Git. La CLI ajoute `langsmith` à la liste
`observability.enabled`; OpenTelemetry peut être ajouté ensuite dans la même liste.

## Générer l'entrypoint LangGraph

```bash
arclith-cli add-adapter --capability agent
```

Répondre:

```text
① Type d'adapter
   1  langgraph

  Votre choix (numéro ou nom): 1
  Nom du graphe LangGraph (agent): todo_agent
  Confirmer la génération ? [y/n] (y): y
```

La CLI crée:

```text
langgraph.json
config/adapters/inbound/langgraph.yaml
src/todo_list_service/adapters/inbound/langgraph/agent.py
```

## Code agent

Remplacer `src/todo_list_service/adapters/inbound/langgraph/agent.py` par:

```python
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from typing import Any, TypedDict

from arclith import Arclith
from arclith.adapters.outbound.pydantic_ai.llm import PydanticAILLMAdapter
from langgraph.graph import END, START

from todo_list_service.application.intent_interpreters.todo_conversation import TodoConversationInterpreter, TodoDraft
from todo_list_service.domain.models.todo import TodoStatus
from todo_list_service.domain.ports.inbound.create_todo import CreateTodoCommand, CreateTodoPort
from todo_list_service.infrastructure.containers.todo_container import build_create_todo_use_case


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    draft: dict[str, Any]
    pending_field: str | None
    answer: str


arclith = Arclith("config")


@lru_cache(maxsize=1)
def _create_todo_use_case() -> CreateTodoPort:
    return build_create_todo_use_case(arclith)


@lru_cache(maxsize=1)
def _intent_interpreter() -> TodoConversationInterpreter:
    lm_settings = arclith.config.adapters.lm
    if lm_settings is None:
        raise RuntimeError("config/adapters/outbound/lm.yaml est requis pour l'agent.")
    return TodoConversationInterpreter(PydanticAILLMAdapter(lm_settings))


def _last_user_message(state: AgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if message.get("role") in {"user", "human"}:
            return str(message.get("content", ""))
    return ""


def _draft_from_state(state: AgentState) -> TodoDraft:
    return TodoDraft.model_validate(state.get("draft", {}))


def _parse_status(raw: str) -> TodoStatus | None:
    normalized = raw.strip().lower()
    aliases = {
        "à faire": TodoStatus.TODO,
        "a faire": TodoStatus.TODO,
        "todo": TodoStatus.TODO,
        "en cours": TodoStatus.WIP,
        "wip": TodoStatus.WIP,
        "terminé": TodoStatus.DONE,
        "termine": TodoStatus.DONE,
        "done": TodoStatus.DONE,
    }
    if normalized in aliases:
        return aliases[normalized]
    try:
        return TodoStatus(normalized)
    except ValueError:
        return None


def _apply_pending_answer(prompt: str, current: TodoDraft, pending_field: str | None) -> tuple[TodoDraft, bool]:
    answer = prompt.strip()
    if not answer or pending_field is None:
        return current, False

    match pending_field:
        case "title":
            return current.model_copy(update={"title": answer}), True
        case "description":
            return current.model_copy(update={"description": answer}), True
        case "status":
            status = _parse_status(answer)
            if status is None:
                return current, False
            return current.model_copy(update={"status": status}), True
        case "due_date":
            try:
                return current.model_copy(update={"due_date": date.fromisoformat(answer)}), True
            except ValueError:
                return current, False
        case "completed_at":
            try:
                return current.model_copy(update={"completed_at": datetime.fromisoformat(answer)}), True
            except ValueError:
                return current, False
        case _:
            return current, False


def _missing_fields(draft: TodoDraft) -> list[str]:
    missing: list[str] = []
    if not draft.title:
        missing.append("title")
    if not draft.description:
        missing.append("description")
    if draft.due_date is None:
        missing.append("due_date")
    if draft.status is None:
        missing.append("status")
    if draft.status == TodoStatus.DONE and draft.completed_at is None:
        missing.append("completed_at")
    return missing


def _question_for(field: str) -> str:
    questions = {
        "title": "Quel est le titre de la todo ?",
        "description": "Quelle description veux-tu enregistrer ?",
        "due_date": "Quelle est la date d'échéance ?",
        "status": "Quel est le statut : todo, wip ou done ?",
        "completed_at": "Quelle est la date de réalisation ?",
    }
    return questions[field]


async def run_agent(state: AgentState) -> AgentState:
    prompt = _last_user_message(state)
    current = _draft_from_state(state)
    pending_field = state.get("pending_field")

    if prompt:
        current, handled_pending = _apply_pending_answer(prompt, current, pending_field)
        if not handled_pending:
            if pending_field:
                prompt = f"Le message utilisateur répond au champ {pending_field!r}: {prompt}"
            extracted = await _intent_interpreter().extract(prompt, current)
            current = current.model_copy(update=extracted.model_dump(exclude_none=True))

    missing = _missing_fields(current)
    if missing:
        pending_field = missing[0]
        answer = _question_for(pending_field)
        messages = [*state.get("messages", []), {"role": "assistant", "content": answer}]
        return {
            **state,
            "draft": current.model_dump(mode="json", exclude_none=True),
            "pending_field": pending_field,
            "answer": answer,
            "messages": messages,
        }

    todo = await _create_todo_use_case().execute(
        CreateTodoCommand(
            title=current.title or "",
            description=current.description or "",
            due_date=current.due_date,
            status=current.status or TodoStatus.TODO,
            completed_at=current.completed_at,
        )
    )
    answer = f"Todo créée: {todo.title} ({todo.uuid})."
    messages = [*state.get("messages", []), {"role": "assistant", "content": answer}]
    return {**state, "draft": {}, "pending_field": None, "answer": answer, "messages": messages}


def register_agent(builder: Any, app: Arclith) -> None:
    builder.add_node("agent", run_agent)
    builder.add_edge(START, "agent")
    builder.add_edge("agent", END)


agent = arclith.langgraph(AgentState, register_agent, name="todo_agent")
```

## Tester l'agent

Lancer LangGraph Studio:

```bash
uv run langgraph dev --no-browser --allow-blocking --port 2024
```

Envoyer un état incomplet:

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

L'agent doit demander le premier champ manquant, par exemple la description ou la date d'échéance.
Répondre ensuite dans le même thread LangGraph: l'état conserve `draft` et `pending_field`, ce qui
permet d'affecter une réponse courte comme `Écrire la doc` au champ qui vient d'être demandé.

Envoyer ensuite un état complet:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "Crée une todo titre Écrire la doc, description couvrir API MCP agent, échéance 2026-09-01, statut todo"
    }
  ]
}
```

Résultat attendu:

```text
Todo créée: Écrire la doc (<uuid>).
```

## Passer à MongoDB ensuite

Avec `repository: memory`, l'API/MCP et LangGraph ne partagent les données que s'ils tournent dans le
même processus. Pour partager entre processus, ajouter MongoDB.

Installer l'extra:

```bash
uv add "arclith[mongodb]"
```

Lancer le wizard:

```bash
arclith-cli add-adapter --capability repository
```

Répondre:

```text
① Type d'adapter
   1  memory
   2  mongodb
   3  duckdb
   4  mariadb

  Votre choix (numéro ou nom): 2

③ Paramètres mongodb
  db_name (todo-list-service): todo_list_service
  multitenant [y/n] (n): n
  Activer mongodb maintenant ? [y/n] (y): y
  Confirmer la génération ? [y/n] (y): y
```

La CLI crée les fichiers repository MongoDB et active:

```yaml
repository: mongodb
```

Configurer l'URI MongoDB via le resolver de secrets local, puis relancer API, MCP et LangGraph.

## Voie rapide

```bash
uv add "arclith[langgraph]"
arclith-cli add-intent-interpreter TodoConversation
arclith-cli add-adapter --capability llm --adapter lmstudio --param model_name="<model-id-lm-studio>" --yes
arclith-cli add-adapter --capability observability --adapter langsmith
arclith-cli add-adapter --capability agent --adapter langgraph --param graph_name=todo_agent --yes

# Ensuite, pour partager les données entre processus:
uv add "arclith[mongodb]"
arclith-cli add-adapter --capability repository --adapter mongodb --entity Todo --db-name todo_list_service --yes
```
