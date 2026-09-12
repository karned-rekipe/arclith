from dataclasses import dataclass
from pathlib import Path

from arclith_cli.guide_models import (
    GuideChoice,
    GuidePlanError,
    NewProjectAnswers,
    ProjectIntent,
    ProjectPlan,
    RepositoryChoice,
)
from arclith_cli.guide_planner import plan_new_project
from arclith_cli.guide_prompts import GuidePrompt
from arclith_cli.rename import EntityNames


@dataclass(frozen=True)
class _IntentAnswers:
    entity: str | None
    usecase: str | None = None
    repository: RepositoryChoice | None = None
    transport_port: int | None = None
    public_path: str | None = None


def ask_new_project_plan(
    prompt: GuidePrompt,
    current_dir: Path,
) -> ProjectPlan:
    """Collect the smallest answer set needed for one complete project intent."""
    intent = ProjectIntent(
        prompt.select(
            "Quel résultat voulez-vous obtenir ?",
            (
                _choice(
                    "Socle minimal",
                    ProjectIntent.MINIMAL.value,
                    "Projet hexagonal vide, avec entité optionnelle.",
                ),
                _choice(
                    "API REST CRUD",
                    ProjectIntent.API_CRUD.value,
                    "Entité, CRUD, repository, FastAPI et routes REST.",
                ),
                _choice(
                    "API REST sur mesure",
                    ProjectIntent.API_CUSTOM.value,
                    "Un cas d'usage explicitement exposé par FastAPI.",
                ),
                _choice(
                    "Serveur MCP",
                    ProjectIntent.MCP.value,
                    "Un outil FastMCP relié à un cas d'usage.",
                ),
                _choice(
                    "Agent LangGraph",
                    ProjectIntent.AGENT.value,
                    "Un graphe typé relié à un cas d'usage.",
                ),
                _choice(
                    "Worker RabbitMQ",
                    ProjectIntent.WORKER.value,
                    "Un consumer versionné relié à un cas d'usage.",
                ),
            ),
        )
    )
    parent_dir = Path(
        _required_text(prompt, "Répertoire parent", default=str(current_dir))
    ).expanduser()
    project_name = _required_text(prompt, "Nom du projet", default="my-service")
    answers = _ask_intent_answers(prompt, intent)
    return plan_new_project(
        NewProjectAnswers(
            parent_dir=parent_dir,
            project_name=project_name,
            intent=intent,
            entity=answers.entity,
            usecase=answers.usecase,
            repository=answers.repository,
            transport_port=answers.transport_port,
            public_path=answers.public_path,
        )
    )


def _ask_intent_answers(
    prompt: GuidePrompt,
    intent: ProjectIntent,
) -> _IntentAnswers:
    if intent == ProjectIntent.MINIMAL:
        entity = (
            _required_text(prompt, "Nom de l'entité", default="Todo")
            if prompt.confirm("Créer une première entité ?", default=True)
            else None
        )
        return _partial_answers(entity=entity)

    entity = _required_text(prompt, "Nom de l'entité", default="Todo")
    repository = _ask_repository(prompt)
    usecase = None
    if intent != ProjectIntent.API_CRUD:
        entity_names = EntityNames.from_input(entity)
        usecase = _required_text(
            prompt,
            "Nom du cas d'usage",
            default=f"Create{entity_names.pascal}",
        )
    port, public_path = _ask_transport_details(prompt, intent, entity)
    return _partial_answers(
        entity=entity,
        usecase=usecase,
        repository=repository,
        transport_port=port,
        public_path=public_path,
    )


def _ask_repository(prompt: GuidePrompt) -> RepositoryChoice:
    return RepositoryChoice(
        prompt.select(
            "Quel repository installer explicitement ?",
            (
                _choice(
                    "Mémoire",
                    RepositoryChoice.MEMORY.value,
                    "Simple pour démarrer et tester, non persistant.",
                ),
                _choice(
                    "MongoDB",
                    RepositoryChoice.MONGODB.value,
                    "Persistance documentaire asynchrone.",
                ),
                _choice(
                    "PostgreSQL JSONB",
                    RepositoryChoice.POSTGRESQL.value,
                    "Persistance relationnelle flexible.",
                ),
            ),
        )
    )


def _ask_transport_details(
    prompt: GuidePrompt,
    intent: ProjectIntent,
    entity: str,
) -> tuple[int | None, str | None]:
    if intent in {ProjectIntent.API_CRUD, ProjectIntent.API_CUSTOM}:
        port = _ask_port(prompt, "Port HTTP", default=8000)
        path = _required_text(
            prompt,
            "Chemin HTTP",
            default=f"/v1/{EntityNames.from_input(entity).snake.replace('_', '-')}",
        )
        return port, path
    if intent == ProjectIntent.MCP:
        return _ask_port(prompt, "Port MCP", default=8001), None
    return None, None


def _partial_answers(
    *,
    entity: str | None,
    usecase: str | None = None,
    repository: RepositoryChoice | None = None,
    transport_port: int | None = None,
    public_path: str | None = None,
) -> _IntentAnswers:
    return _IntentAnswers(
        entity=entity,
        usecase=usecase,
        repository=repository,
        transport_port=transport_port,
        public_path=public_path,
    )


def _ask_port(prompt: GuidePrompt, label: str, *, default: int) -> int:
    raw = _required_text(prompt, label, default=str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise GuidePlanError(f"{label} doit être un entier.") from exc
    if not 1 <= value <= 65535:
        raise GuidePlanError(f"{label} doit être compris entre 1 et 65535.")
    return value


def _required_text(prompt: GuidePrompt, message: str, *, default: str = "") -> str:
    value = prompt.text(message, default=default)
    if not value:
        raise GuidePlanError(f"{message} ne peut pas être vide.")
    return value


def _choice(title: str, value: str, description: str) -> GuideChoice:
    return GuideChoice(title=title, value=value, description=description)
