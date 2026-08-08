# 6.3 Définir l'état et le parsing local

Intention: poser la mémoire courte du graphe et les fonctions déterministes qui ne justifient pas un
appel LLM.

## State

Créer le package LangGraph:

```bash
mkdir -p src/todo_list_service/adapters/inbound/langgraph
touch src/todo_list_service/adapters/inbound/langgraph/__init__.py
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

## Parsing local

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

Étape suivante: [détecter l'action et collecter le draft](06-agent-action-collection.md).
