# 6.2 Écrire les intent-interpreters

Intention: séparer la décision d'action de l'extraction des champs. Le premier interpréteur choisit
une action supportée; le second extrait un brouillon de todo.

## Action

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
                "Retourne create_todo quand il veut creer, ajouter ou enregistrer une tâche. "
                "Retourne list_todos quand il veut afficher, lister ou consulter les tâches existantes. "
                "Retourne cancel_todo_creation quand il annule une creation de todo en cours. "
                "Retourne unknown quand l'intention n'est pas une action todo prise en charge."
            ),
        )
```

## Conversation

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

Étape suivante: [définir l'état et le parsing local](06-agent-state-parsing.md).
