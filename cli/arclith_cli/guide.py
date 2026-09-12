import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from click.exceptions import Exit
from rich.console import Console

from arclith_cli.capabilities import CAPABILITY_CATALOG, get_capability
from arclith_cli.capability_models import AdapterSpec, ParameterSpec
from arclith_cli.guide_creation import ask_new_project_plan
from arclith_cli.guide_executor import execute_project_plan
from arclith_cli.guide_models import (
    GuideCancelled,
    GuideChoice,
    GuidePlanError,
    GuideStep,
    ProjectOverview,
    ProjectPlan,
)
from arclith_cli.guide_planner import (
    plan_add_adapter,
    plan_add_entity,
    plan_add_usecase,
    plan_existing_steps,
    plan_expose_feature,
    plan_expose_usecase,
)
from arclith_cli.guide_prompts import GuidePrompt, QuestionaryGuidePrompt
from arclith_cli.guide_rendering import GuideRenderer
from arclith_cli.guide_replay import replay_recipe_from_prompt, show_history
from arclith_cli.guide_status import find_project_root, inspect_project
from arclith_cli.recipe import RECIPE_FILENAME

_TRANSPORT_ADAPTERS = {
    "api/fastapi": "fastapi",
    "mcp/fastmcp": "fastmcp",
    "agent/langgraph": "langgraph",
    "command-bus/rabbitmq": "rabbitmq",
}


def should_launch_guide(
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    environ: Mapping[str, str] = os.environ,
) -> bool:
    """Keep scripts stable while making the no-argument TTY experience guided."""
    return (
        stdin.isatty() and stdout.isatty() and environ.get("TERM", "").lower() != "dumb"
    )


def run_interactive_guide(
    *,
    start_dir: Path | None = None,
    prompt: GuidePrompt | None = None,
    console: Console | None = None,
) -> None:
    """Run the persistent project guide until the user explicitly leaves it."""
    resolved_console = console or Console()
    renderer = GuideRenderer(resolved_console)
    resolved_prompt = prompt or QuestionaryGuidePrompt()
    current_dir = (start_dir or Path.cwd()).resolve()
    project_dir = find_project_root(current_dir)
    renderer.welcome()
    while True:
        try:
            if project_dir is None:
                project_dir, keep_running = _outside_project_menu(
                    resolved_prompt,
                    renderer,
                    current_dir,
                )
            else:
                project_dir, keep_running = _project_menu(
                    resolved_prompt,
                    renderer,
                    project_dir,
                )
            if not keep_running:
                return
        except GuideCancelled:
            renderer.warning("Guide fermé. Aucun choix en attente n'a été appliqué.")
            return
        except (GuidePlanError, OSError, SyntaxError, ValueError, Exit) as exc:
            message = _guide_error_message(exc)
            if message is not None:
                renderer.error(message)


def _guide_error_message(exc: Exception) -> str | None:
    if isinstance(exc, Exit):
        if exc.exit_code == 0:
            return None
        return "L'étape Arclith a été refusée ; le guide reste ouvert."
    return str(exc)


def _outside_project_menu(
    prompt: GuidePrompt,
    renderer: GuideRenderer,
    current_dir: Path,
) -> tuple[Path | None, bool]:
    action = prompt.select(
        "Que voulez-vous faire ?",
        (
            _choice(
                "Créer un projet complet",
                "create",
                "Choisir un résultat, vérifier le plan, puis générer.",
            ),
            _choice(
                "Rejouer une recette",
                "replay",
                f"Reconstruire un projet depuis {RECIPE_FILENAME}.",
            ),
            _choice(
                "Explorer les capacités",
                "capabilities",
                "Voir les technologies disponibles sans rien installer.",
            ),
            _choice(
                "Voir les commandes avancées",
                "advanced",
                "Continuer à utiliser chaque commande directement.",
            ),
            _choice("Quitter", "quit", "Rendre la main au terminal."),
        ),
    )
    if action == "quit":
        return None, False
    if action == "capabilities":
        renderer.capabilities()
        return None, True
    if action == "advanced":
        renderer.advanced_commands()
        return None, True
    if action == "replay":
        return replay_recipe_from_prompt(prompt, renderer, current_dir), True
    plan = ask_new_project_plan(prompt, current_dir)
    renderer.plan(plan)
    if not prompt.confirm("Appliquer ce plan ?", default=True):
        renderer.warning("Plan annulé ; aucun fichier n'a été créé.")
        return None, True
    result = execute_project_plan(plan, on_step=renderer.progress)
    renderer.success(f"Projet complet créé dans {result.root}")
    renderer.warning(f"Pour votre shell : cd {result.root}")
    return result.root, True


def _project_menu(
    prompt: GuidePrompt,
    renderer: GuideRenderer,
    project_dir: Path,
) -> tuple[Path | None, bool]:
    overview = inspect_project(project_dir)
    renderer.overview(overview)
    action = prompt.select(
        "Prochaine étape",
        (
            _choice("Ajouter une entité", "entity", "Profil minimal ou CRUD."),
            _choice(
                "Ajouter un cas d'usage",
                "usecase",
                "Port inbound et implémentation applicative.",
            ),
            _choice(
                "Ajouter un adapter",
                "adapter",
                "Catalogue complet, profils et paramètres.",
            ),
            _choice(
                "Exposer un cas d'usage",
                "expose-usecase",
                "FastAPI, FastMCP, LangGraph ou RabbitMQ.",
                disabled=(
                    None if overview.usecases else "ajoutez d'abord un cas d'usage"
                ),
            ),
            _choice(
                "Exposer une feature CRUD",
                "expose-feature",
                "Projeter toutes les opérations vers FastAPI.",
                disabled=(
                    None
                    if overview.features and overview.has_adapter("api", "fastapi")
                    else "feature CRUD et adapter FastAPI requis"
                ),
            ),
            _choice("Vérifier le projet", "doctor", "Relire l'état et les manifestes."),
            _choice(
                "Voir l'historique", "history", "Afficher la recette reproductible."
            ),
            _choice(
                "Menu projets",
                "back",
                "Créer ailleurs, rejouer une recette ou explorer le catalogue.",
            ),
            _choice("Quitter", "quit", "Rendre la main au terminal."),
        ),
    )
    if action == "quit":
        return project_dir, False
    if action == "back":
        return None, True
    if action == "doctor":
        if overview.issues:
            renderer.warning("Le diagnostic a trouvé les points listés ci-dessus.")
        else:
            renderer.success("Structure, manifestes et recette sont lisibles.")
        return project_dir, True
    if action == "history":
        show_history(renderer, project_dir)
        return project_dir, True

    plan = _ask_existing_plan(prompt, overview, action)
    renderer.plan(plan)
    if not prompt.confirm("Appliquer cette étape ?", default=True):
        renderer.warning("Étape annulée ; aucun changement demandé.")
        return project_dir, True
    execute_project_plan(plan, on_step=renderer.progress)
    renderer.success("Étape appliquée et ajoutée à la recette.")
    return project_dir, True


def _ask_existing_plan(
    prompt: GuidePrompt,
    overview: ProjectOverview,
    action: str,
) -> ProjectPlan:
    if action == "entity":
        entity = _required_text(prompt, "Nom de l'entité", default="Todo")
        profile = prompt.select(
            "Profil applicatif initial",
            (
                _choice("Minimal", "minimal", "Entité seule."),
                _choice("CRUD", "crud", "Ports et cas d'usage CRUD complets."),
            ),
        )
        step = plan_add_entity(entity, profile)
    elif action == "usecase":
        step = _ask_usecase_step(prompt, overview.entities)
    elif action == "adapter":
        step = _ask_adapter_step(prompt, overview.root)
    elif action == "expose-usecase":
        step = _ask_binding_step(prompt, overview)
    elif action == "expose-feature":
        feature = prompt.select(
            "Feature à exposer",
            tuple(
                _choice(item.name, item.name, f"{item.entity} — {item.blueprint}")
                for item in overview.features
            ),
        )
        path = _required_text(
            prompt,
            "Chemin HTTP",
            default=f"/v1/{feature.replace('_', '-')}",
        )
        step = plan_expose_feature(feature, path)
    else:
        raise GuidePlanError(f"Action du guide non supportée : {action}")
    return plan_existing_steps(overview.root, (step,))


def _ask_usecase_step(
    prompt: GuidePrompt,
    entities: tuple[str, ...],
) -> GuideStep:
    usecase = _required_text(prompt, "Nom du cas d'usage", default="CreateTodo")
    options = tuple(
        _choice(entity, f"entity:{entity}", "Lier à cette entité existante.")
        for entity in entities
    ) + (
        _choice("Créer une nouvelle entité", "new", "Créer puis lier l'entité."),
        _choice("Cas transverse", "none", "Aucun repository métier."),
    )
    mode = prompt.select("Entité métier", options)
    if mode.startswith("entity:"):
        return plan_add_usecase(
            usecase,
            entity=mode.removeprefix("entity:"),
            new_entity=None,
            no_entity=False,
        )
    if mode == "new":
        return plan_add_usecase(
            usecase,
            entity=None,
            new_entity=_required_text(prompt, "Nouvelle entité", default="Todo"),
            no_entity=False,
        )
    return plan_add_usecase(
        usecase,
        entity=None,
        new_entity=None,
        no_entity=True,
    )


def _ask_adapter_step(prompt: GuidePrompt, project_dir: Path) -> GuideStep:
    capability_name = prompt.select(
        "Capacité à installer",
        tuple(
            _choice(item.name, item.name, item.description)
            for item in CAPABILITY_CATALOG
        ),
    )
    capability = get_capability(capability_name)
    if capability is None:
        raise GuidePlanError(f"Capacité inconnue : {capability_name}")
    adapter_name = prompt.select(
        "Technologie",
        tuple(
            _choice(adapter.name, adapter.name, adapter.description)
            for adapter in capability.adapters
        ),
    )
    adapter = capability.get_adapter(adapter_name)
    if adapter is None:
        raise GuidePlanError(f"Adapter inconnu : {adapter_name}")
    profile: str | None = None
    if adapter.profiles:
        selected = prompt.select(
            "Profil de configuration",
            (_choice("Valeurs par défaut", "", "Paramètres catalogue."),)
            + tuple(
                _choice(item.name, item.name, "Profil prédéfini.")
                for item in adapter.profiles
            ),
        )
        profile = selected or None
    customize = prompt.confirm("Personnaliser les paramètres ?", default=False)
    params, secret_params = _ask_adapter_params(
        prompt,
        adapter,
        project_dir,
        profile=profile,
        customize=customize,
    )
    return plan_add_adapter(
        capability.name,
        adapter.name,
        params=params,
        profile=profile,
        secret_params=secret_params,
    )


def _ask_adapter_params(
    prompt: GuidePrompt,
    adapter: AdapterSpec,
    project_dir: Path,
    *,
    profile: str | None,
    customize: bool,
) -> tuple[dict[str, str], frozenset[str]]:
    profile_values: Mapping[str, str | bool] = {}
    if profile is not None:
        selected_profile = adapter.get_profile(profile)
        if selected_profile is not None:
            profile_values = selected_profile.values()
    params: dict[str, str] = {}
    secret_params: set[str] = set()
    for parameter in adapter.parameters:
        covered = parameter.name in profile_values
        must_ask = (
            parameter.required
            and not covered
            and not _parameter_default(parameter, project_dir)
        )
        if not customize and not must_ask:
            continue
        params[parameter.name] = _ask_parameter(prompt, parameter, project_dir)
        if parameter.secret:
            secret_params.add(parameter.name)
    return params, frozenset(secret_params)


def _ask_parameter(
    prompt: GuidePrompt,
    parameter: ParameterSpec,
    project_dir: Path,
) -> str:
    default = _parameter_default(parameter, project_dir)
    if parameter.kind == "boolean":
        return _ask_boolean_parameter(prompt, parameter, default)
    value = _ask_string_parameter(prompt, parameter, default)
    if parameter.required and not value:
        raise GuidePlanError(f"Paramètre requis manquant : {parameter.name}")
    return value


def _ask_boolean_parameter(
    prompt: GuidePrompt,
    parameter: ParameterSpec,
    default: str,
) -> str:
    normalized = default.lower()
    enabled = prompt.confirm(
        parameter.prompt,
        default=normalized in {"1", "true", "yes", "on"},
    )
    return "true" if enabled else "false"


def _ask_string_parameter(
    prompt: GuidePrompt,
    parameter: ParameterSpec,
    default: str,
) -> str:
    if parameter.choices and parameter.csv_choices:
        defaults = set(default.split(","))
        selected = prompt.checkbox(
            parameter.prompt,
            tuple(
                GuideChoice(
                    title=value,
                    value=value,
                    description="",
                    checked=value in defaults,
                )
                for value in parameter.choices
            ),
        )
        return ",".join(selected)
    if parameter.choices:
        return prompt.select(
            parameter.prompt,
            tuple(
                GuideChoice(
                    title=value,
                    value=value,
                    description="",
                    checked=value == default,
                )
                for value in parameter.choices
            ),
        )
    return prompt.text(
        parameter.prompt,
        default="" if parameter.secret else default,
        secret=parameter.secret,
    )


def _ask_binding_step(
    prompt: GuidePrompt,
    overview: ProjectOverview,
) -> GuideStep:
    usecase = prompt.select(
        "Cas d'usage à exposer",
        tuple(
            _choice(item, item, "Port inbound existant.") for item in overview.usecases
        ),
    )
    transports = tuple(
        _choice(adapter, via, f"Adapter installé : {adapter}")
        for adapter, via in _TRANSPORT_ADAPTERS.items()
        if adapter in overview.adapters
    )
    if not transports:
        raise GuidePlanError(
            "Installez d'abord FastAPI, FastMCP, LangGraph ou RabbitMQ."
        )
    via = prompt.select("Transport", transports)
    default_feature = _feature_from_usecase(usecase)
    feature = _required_text(
        prompt, "Nom stable de la feature", default=default_feature
    )
    public_name = prompt.text("Nom public (vide = nom du cas d'usage)") or None
    http_path: str | None = None
    method: str | None = None
    status_code = 200
    command_type: str | None = None
    if via == "fastapi":
        http_path = _required_text(
            prompt,
            "Chemin HTTP",
            default=f"/v1/{feature.replace('_', '-')}",
        )
        method = prompt.select(
            "Méthode HTTP",
            tuple(
                _choice(value, value, "")
                for value in ("POST", "GET", "PUT", "PATCH", "DELETE")
            ),
        )
        status_code = _ask_status_code(
            prompt,
            default=201 if method == "POST" else 200,
        )
    elif via == "rabbitmq":
        command_type = _required_text(
            prompt,
            "Type de commande versionné",
            default=f"{feature}.{usecase}.v1",
        )
    return plan_expose_usecase(
        usecase,
        via=via,
        feature=feature,
        public_name=public_name,
        http_path=http_path,
        method=method,
        status_code=status_code,
        command_type=command_type,
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


def _ask_status_code(prompt: GuidePrompt, *, default: int) -> int:
    raw = _required_text(prompt, "Statut HTTP", default=str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise GuidePlanError("Le statut HTTP doit être un entier.") from exc
    return value


def _required_text(prompt: GuidePrompt, message: str, *, default: str = "") -> str:
    value = prompt.text(message, default=default)
    if not value:
        raise GuidePlanError(f"{message} ne peut pas être vide.")
    return value


def _parameter_default(parameter: ParameterSpec, project_dir: Path) -> str:
    if parameter.default_from_project_name:
        return project_dir.name
    if isinstance(parameter.default, bool):
        return "true" if parameter.default else "false"
    return parameter.default or ""


def _feature_from_usecase(usecase: str) -> str:
    for prefix in ("create_", "get_", "list_", "update_", "delete_"):
        if usecase.startswith(prefix) and len(usecase) > len(prefix):
            return usecase.removeprefix(prefix)
    return usecase


def _choice(
    title: str,
    value: str,
    description: str,
    *,
    disabled: str | None = None,
) -> GuideChoice:
    return GuideChoice(
        title=title,
        value=value,
        description=description,
        disabled=disabled,
    )


def guide_command() -> None:
    """Lancer le guide persistant pour créer ou faire évoluer un projet."""
    run_interactive_guide()
