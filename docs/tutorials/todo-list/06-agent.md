# 6. Ajouter un agent

Objectif: créer un agent LangGraph qui comprend une demande en langage naturel, choisit l'action
todo à exécuter, collecte seulement les champs vraiment manquants, puis appelle les mêmes ports
inbound que l'API et le MCP.

![Capture interactive agent](assets/06-agent.svg)

L'agent a quatre responsabilités:

- classifier l'intention: créer une todo, lister les todos, annuler une création en cours ou répondre
  que la demande n'est pas prise en charge;
- transformer une conversation en `TodoDraft`;
- conserver `draft` et `pending_field` dans l'état LangGraph pendant la phase de questionnement;
- appeler `CreateTodoPort` ou `ListTodosPort`.

Il ne connaît pas la persistance. Il ne parle ni à MongoDB ni au repository directement.

```text
message utilisateur
  -> adapter LangGraph
  -> intent-interpreter / parsing local
  -> CreateTodoPort ou ListTodosPort
  -> use case applicatif
  -> Repository[Todo]
```

## Installer les dépendances agent

```bash
uv add "arclith[langgraph]"
```

## Créer les intent-interpreters

Depuis la racine du projet, créer le package puis deux interpréteurs:

```bash
touch src/todo_list_service/application/intent_interpreters/__init__.py
arclith-cli add-intent-interpreter
arclith-cli add-intent-interpreter
```

Répondre:

```text
Interpréteur d'intention (ex : IngredientIntent, todo_intent)
  Nom de l'interpréteur: TodoAction

Interpréteur d'intention (ex : IngredientIntent, todo_intent)
  Nom de l'interpréteur: TodoConversation
```

Les deux fichiers ne font pas le même travail:

| Fichier | Rôle |
| --- | --- |
| `application/intent_interpreters/todo_action.py` | Classe l'action globale: créer, lister, annuler ou inconnu. C'est le fallback LLM quand le fast path local n'est pas assez sûr. |
| `application/intent_interpreters/todo_conversation.py` | Extrait les champs d'une todo dans un `TodoDraft`: titre, échéance, description, statut, date de réalisation. |

Le graphe peut router vite les cas évidents, puis appeler l'extraction uniquement quand l'action est
bien une création de todo.

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

Vérifier `config/adapters/outbound/lm.yaml`:

```yaml
provider: openai
model_name: "mistralai/ministral-3-3b"
api_key: "lm-studio"
base_url: "http://127.0.0.1:1234/v1"
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
  Activer langsmith [y/n] (y): y
  Confirmer la génération ? [y/n] (y): y
```

Vérifier `config/adapters/outbound/langsmith.yaml`:

```yaml
tracing: true
project: "todo-list-service"
endpoint: "https://api.smith.langchain.com"
api_key_env: LANGSMITH_API_KEY
studio: langgraph
langgraph_api_min_version: "0.11.0"
```

La clé reste dans `.env`, jamais dans Git. LangSmith sert à observer l'agent:

- LangGraph exécute le graphe localement;
- LM Studio fournit le modèle local;
- LangSmith affiche les runs, les messages, les appels LLM et les erreurs.

![Flux LangGraph et LangSmith](assets/06-langsmith-flow.svg)

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

Vérifier `config/adapters/inbound/langgraph.yaml`:

```yaml
name: "todo_agent"
graph: "todo_agent"
entrypoint: "./src/todo_list_service/adapters/inbound/langgraph/agent.py:agent"
env: ".env"
```

Modifier `langgraph.json`:

```json
{
  "dependencies": ["."],
  "graphs": {
    "todo_agent": "./src/todo_list_service/adapters/inbound/langgraph/agent.py:agent"
  },
  "env": ".env"
}
```

## Rôle des fichiers LangGraph

Créer le package:

```bash
mkdir -p src/todo_list_service/adapters/inbound/langgraph
touch src/todo_list_service/adapters/inbound/langgraph/__init__.py
```

| Fichier | Rôle |
| --- | --- |
| `agent.py` | Assemble le graphe LangGraph, déclare les noeuds et expose l'objet `agent` utilisé par `langgraph.json`. |
| `state.py` | Définit `AgentState`, lit le dernier message utilisateur, reconstruit un `TodoDraft` depuis l'état, fabrique les messages assistant. |
| `dependencies.py` | Centralise l'instance `Arclith`, l'adapter LLM et les ports applicatifs, avec cache local par process. |
| `nodes.py` | Contient les fonctions de noeuds: router l'intention, collecter les champs, créer, lister, annuler, répondre inconnu. |
| `routing.py` | Contient les fonctions de conditional edges LangGraph. |
| `intent.py` | Fait la détection locale haute confiance, puis laisse les cas ambigus au LLM. |
| `collection.py` | Met à jour le draft, applique les défauts, détecte les champs manquants et génère la prochaine question. |
| `parsing.py` | Normalise le français, détecte les dates relatives, les statuts, l'annulation et les titres simples. |
| `formatters.py` | Transforme le résultat de `ListTodosUseCase` en réponse lisible pour l'utilisateur et en payload JSON. |

## Code LangGraph

Modifier `src/todo_list_service/application/intent_interpreters/todo_action.py`:

```python
from enum import StrEnum

from arclith.domain.ports.outbound.llm import LLMPort
from pydantic import BaseModel, Field


class TodoAction(StrEnum):
    CREATE_TODO = "create_todo"
    LIST_TODOS = "list_todos"
    CANCEL_TODO_CREATION = "cancel_todo_creation"
    UNKNOWN = "unknown"


class TodoActionDecision(BaseModel):
    action: TodoAction = Field(default=TodoAction.UNKNOWN)


class TodoActionInterpreter:
    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def classify(self, prompt: str) -> TodoActionDecision:
        return await self._llm.complete_structured(
            prompt,
            output_type=TodoActionDecision,
            instructions=(
                "Tu classes l'intention d'un utilisateur qui parle a un agent de gestion de todos. "
                "Retourne create_todo quand il veut creer, ajouter ou enregistrer une tache. "
                "Retourne list_todos quand il veut afficher, lister ou consulter les taches existantes. "
                "Retourne cancel_todo_creation quand il annule une creation de todo en cours. "
                "Retourne unknown quand l'intention n'est pas une action todo prise en charge."
            ),
        )
```

Modifier `src/todo_list_service/application/intent_interpreters/todo_conversation.py`:

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
        today = date.today()
        return await self._llm.complete_structured(
            prompt,
            output_type=TodoDraft,
            instructions=(
                "Tu extrais les champs d'une todo a partir d'une conversation en francais. "
                "Quand la demande est de type 'ajoute une todo pour X' ou 'cree une todo pour X', "
                "X est le titre de la todo, sauf si l'utilisateur dit explicitement que c'est une description. "
                "Quand l'utilisateur dit 'je dois X', X est le titre de la todo. "
                f"Date courante: {today.isoformat()}. Interprete les dates relatives comme 'demain'. "
                "Si aucune description n'est explicite, laisse la description vide. "
                "Si aucun statut n'est explicite, utilise todo. "
                "Retourne uniquement les champs explicitement presents ou clairement deduits. "
                "Ne fabrique pas de titre ou de date. "
                f"Draft actuel: {current.model_dump_json(exclude_none=True)}"
            ),
        )
```

Modifier `src/todo_list_service/adapters/inbound/langgraph/state.py`:

```python
from typing import Any

from langgraph.graph import MessagesState

from todo_list_service.application.intent_interpreters.todo_action import TodoAction
from todo_list_service.application.intent_interpreters.todo_conversation import TodoDraft

type AgentAction = TodoAction


class AgentState(MessagesState, total=False):
    action: AgentAction
    draft: dict[str, Any]
    pending_field: str | None
    answer: str
    todos: list[dict[str, Any]]


def last_user_message(state: AgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if message_role(message) in {"user", "human"}:
            return message_content(message)
    return ""


def message_role(message: Any) -> str | None:
    if isinstance(message, dict):
        role = message.get("role")
        return str(role) if role is not None else None

    role = getattr(message, "type", None)
    return str(role) if role is not None else None


def message_content(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content", ""))

    content = getattr(message, "content", "")
    return content if isinstance(content, str) else str(content)


def assistant_message(content: str) -> dict[str, str]:
    return {"role": "assistant", "content": content}


def draft_from_state(state: AgentState) -> TodoDraft:
    return TodoDraft.model_validate(state.get("draft", {}))
```

Modifier `src/todo_list_service/adapters/inbound/langgraph/parsing.py`:

```python
import re
from datetime import date, timedelta
from unicodedata import combining, normalize

from todo_list_service.domain.models.todo import TodoStatus

_TITLE_PREFIXES = (
    r"ajoute(?:r)?(?:\s+une)?(?:\s+tache|\s+todo)?(?:\s+pour)?",
    r"cree(?:r)?(?:\s+une)?(?:\s+tache|\s+todo)?(?:\s+pour)?",
    r"je\s+dois",
    r"il\s+faut(?:\s+que\s+je)?",
    r"pense\s+a",
    r"rappelle(?:\s+moi)?(?:\s+de)?",
)
_RELATIVE_DATE_PATTERNS = (
    r"\bapres\s+demain\b",
    r"\bdemain\b",
    r"\baujourd\s+hui\b",
)
_CANCEL_MARKERS = (
    "annule",
    "annuler",
    "laisse tomber",
    "stop",
    "abandonne",
    "abandonner",
    "finalement non",
)


def normalize_user_text(raw: str) -> str:
    decomposed = normalize("NFKD", raw.casefold())
    normalized = "".join(character for character in decomposed if not combining(character))
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def parse_status(raw: str) -> TodoStatus | None:
    normalized = normalize_user_text(raw.strip())
    aliases = {
        "a faire": TodoStatus.TODO,
        "todo": TodoStatus.TODO,
        "en cours": TodoStatus.WIP,
        "wip": TodoStatus.WIP,
        "termine": TodoStatus.DONE,
        "done": TodoStatus.DONE,
    }
    if normalized in aliases:
        return aliases[normalized]

    for status in TodoStatus:
        if status.value == normalized:
            return status
    return None


def parse_relative_due_date(raw: str, today: date | None = None) -> date | None:
    normalized = normalize_user_text(raw)
    reference_date = today or date.today()
    if "apres demain" in normalized:
        return reference_date + timedelta(days=2)
    if "demain" in normalized:
        return reference_date + timedelta(days=1)
    if "aujourd hui" in normalized:
        return reference_date
    return None


def is_cancel_request(raw: str) -> bool:
    normalized = normalize_user_text(raw)
    return any(marker in normalized for marker in _CANCEL_MARKERS)


def extract_title_hint(raw: str) -> str | None:
    normalized = normalize_user_text(raw)
    without_prefix = normalized
    for prefix in _TITLE_PREFIXES:
        without_prefix = re.sub(rf"^{prefix}\s+", "", without_prefix)

    without_date = without_prefix
    for pattern in _RELATIVE_DATE_PATTERNS:
        without_date = re.sub(pattern, "", without_date)

    title = re.sub(r"\s+", " ", without_date).strip()
    return title if title else None
```

Modifier `src/todo_list_service/adapters/inbound/langgraph/intent.py`:

```python
from todo_list_service.adapters.inbound.langgraph.parsing import is_cancel_request, normalize_user_text
from todo_list_service.adapters.inbound.langgraph.state import AgentAction, AgentState
from todo_list_service.application.intent_interpreters.todo_action import TodoAction

LIST_INTENT_MARKERS = (
    "affiche",
    "lister",
    "liste",
    "montre",
    "voir",
    "recap",
)
LIST_QUESTION_MARKERS = (
    "qu est ce que je dois faire",
    "que dois je faire",
    "quoi faire",
    "ce que je dois faire",
)
TODO_TARGET_MARKERS = (
    "todo",
    "todos",
    "tache",
    "taches",
)
CREATE_INTENT_MARKERS = (
    "ajoute",
    "ajouter",
    "cree",
    "creer",
    "nouvelle",
    "nouveau",
    "pense a",
    "rappelle",
)
CREATE_PREFIX_MARKERS = (
    "je dois",
    "j ai besoin de",
    "il faut",
    "il faut que je",
)


def has_intent_marker(normalized: str, markers: tuple[str, ...]) -> bool:
    words = set(normalized.split())
    for marker in markers:
        if " " in marker:
            if marker in normalized:
                return True
        elif marker in words:
            return True
    return False


def has_prefix_marker(normalized: str, markers: tuple[str, ...]) -> bool:
    return any(normalized == marker or normalized.startswith(f"{marker} ") for marker in markers)


def detect_high_confidence_action(prompt: str, state: AgentState) -> AgentAction:
    has_todo_draft = bool(state.get("pending_field") or state.get("draft"))
    if has_todo_draft and is_cancel_request(prompt):
        return TodoAction.CANCEL_TODO_CREATION
    if state.get("pending_field") or state.get("draft"):
        return TodoAction.CREATE_TODO

    normalized = normalize_user_text(prompt)
    targets_todo_domain = has_intent_marker(normalized, TODO_TARGET_MARKERS)
    if has_intent_marker(normalized, LIST_QUESTION_MARKERS):
        return TodoAction.LIST_TODOS
    if has_intent_marker(normalized, LIST_INTENT_MARKERS) and targets_todo_domain:
        return TodoAction.LIST_TODOS
    if has_prefix_marker(normalized, CREATE_PREFIX_MARKERS):
        return TodoAction.CREATE_TODO
    if has_intent_marker(normalized, CREATE_INTENT_MARKERS):
        return TodoAction.CREATE_TODO
    return TodoAction.UNKNOWN
```

Modifier `src/todo_list_service/adapters/inbound/langgraph/collection.py`:

```python
from datetime import date, datetime

from todo_list_service.adapters.inbound.langgraph.parsing import extract_title_hint, parse_relative_due_date, parse_status
from todo_list_service.application.intent_interpreters.todo_conversation import TodoDraft
from todo_list_service.domain.models.todo import TodoStatus


def enrich_draft_from_prompt(prompt: str, current: TodoDraft) -> TodoDraft:
    updates: dict[str, object] = {}
    if not current.title:
        title = extract_title_hint(prompt)
        if title is not None:
            updates["title"] = title

    if current.due_date is None:
        due_date = parse_relative_due_date(prompt)
        if due_date is not None:
            updates["due_date"] = due_date

    return current.model_copy(update=updates) if updates else current


def apply_default_fields(draft: TodoDraft) -> TodoDraft:
    updates: dict[str, object] = {}
    if draft.description is None:
        updates["description"] = ""
    if draft.status is None:
        updates["status"] = TodoStatus.TODO
    return draft.model_copy(update=updates) if updates else draft


def apply_pending_answer(prompt: str, current: TodoDraft, pending_field: str | None) -> tuple[TodoDraft, bool]:
    answer = prompt.strip()
    if not answer or pending_field is None:
        return current, False

    match pending_field:
        case "title":
            return current.model_copy(update={"title": answer}), True
        case "description":
            return current.model_copy(update={"description": answer}), True
        case "status":
            status = parse_status(answer)
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


def missing_fields(draft: TodoDraft) -> list[str]:
    missing: list[str] = []
    if not draft.title:
        missing.append("title")
    if draft.due_date is None:
        missing.append("due_date")
    if draft.status == TodoStatus.DONE and draft.completed_at is None:
        missing.append("completed_at")
    return missing


def question_for(field: str) -> str:
    questions = {
        "title": "Quel est le titre de la todo ?",
        "due_date": "Quelle est la date d'echeance ?",
        "completed_at": "Quelle est la date de realisation ?",
    }
    return questions[field]
```

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

## Fast path local et fallback LLM

Le noeud `route_intent` suit cette règle:

1. essayer `detect_high_confidence_action(prompt, state)`;
2. si le résultat est sûr, router sans appeler le LLM;
3. sinon appeler `TodoActionInterpreter.classify()`.

Exemples de fast path:

| Message | Action |
| --- | --- |
| `Liste mes todos` | `LIST_TODOS` |
| `Qu'est ce que je dois faire aujourd'hui ?` | `LIST_TODOS` |
| `Je dois acheter des bananes demain` | `CREATE_TODO` |
| `Annule` pendant une création | `CANCEL_TODO_CREATION` |

Le fallback LLM reste nécessaire pour les formulations ambiguës. Il ne persiste rien: il retourne
seulement une décision structurée.

## Tests agent

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

## Tester dans LangGraph Studio

Lancer LangGraph Studio:

```bash
uv run langgraph dev --no-browser --allow-blocking --port 2024
```

Le terminal affiche une URL de ce type:

```text
https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

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

## Voie rapide

```bash
uv add "arclith[langgraph]"
arclith-cli add-intent-interpreter TodoAction
arclith-cli add-intent-interpreter TodoConversation
arclith-cli add-adapter --capability llm --adapter lmstudio --param model_name="<model-id-lm-studio>" --yes
arclith-cli add-adapter --capability observability --adapter langsmith
arclith-cli add-adapter --capability agent --adapter langgraph --param graph_name=todo_agent --yes
```

Étape suivante: [annexes locales](07-local-services.md).
