# 6.4 Détecter l'action et collecter le draft

Intention: router rapidement les demandes évidentes, puis compléter le brouillon de todo en posant
uniquement les questions nécessaires.

## Détection d'action

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

Le noeud `route_intent` applique cette règle:

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

## Collecte de draft

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

Les défauts sont appliqués ici:

- si aucune description n'est explicite, `description=""`;
- si aucun statut n'est explicite, `status=todo`;
- `completed_at` n'est demandé que si `status=done`;
- `due_date` reste obligatoire.

Étape suivante: [formatter, router et injecter les dépendances](06-agent-routing-dependencies.md).
