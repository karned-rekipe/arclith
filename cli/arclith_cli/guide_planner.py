import re
import shlex
from collections.abc import Mapping
from pathlib import Path

from arclith_cli.application_blueprint_cli import (
    application_profile_recipe_metadata,
)
from arclith_cli.guide_models import (
    GuidePlanError,
    GuideStep,
    NewProjectAnswers,
    ProjectIntent,
    ProjectPlan,
    RepositoryChoice,
)
from arclith_cli.rename import EntityNames

_COMPONENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_SUPPORTED_REPOSITORIES = frozenset(RepositoryChoice)


def plan_new_project(answers: NewProjectAnswers) -> ProjectPlan:
    """Build a complete, deterministic plan without touching the filesystem."""
    _validate_answers(answers)
    target_dir = answers.parent_dir / answers.project_name
    steps = [_init_step(answers.project_name, answers.parent_dir)]
    if answers.intent == ProjectIntent.MINIMAL:
        if answers.entity is not None:
            steps.append(_entity_step(answers.entity, profile="minimal"))
        return ProjectPlan(
            target_dir=target_dir,
            intent=answers.intent,
            steps=tuple(steps),
            creates_project=True,
        )

    assert answers.entity is not None
    assert answers.repository is not None
    if answers.intent == ProjectIntent.API_CRUD:
        assert answers.public_path is not None
        assert answers.transport_port is not None
        steps.extend(
            (
                _entity_step(answers.entity, profile="crud"),
                _adapter_step("repository", answers.repository.value, params={}),
                _adapter_step(
                    "api",
                    "fastapi",
                    params={"port": str(answers.transport_port)},
                ),
                _feature_step(answers.entity, answers.public_path),
            )
        )
    else:
        assert answers.usecase is not None
        steps.extend(
            (
                _entity_step(answers.entity, profile="minimal"),
                _usecase_step(answers.usecase, answers.entity),
                _adapter_step("repository", answers.repository.value, params={}),
                _transport_step(answers),
                _binding_step(answers),
            )
        )
    return ProjectPlan(
        target_dir=target_dir,
        intent=answers.intent,
        steps=tuple(steps),
        creates_project=True,
    )


def plan_existing_steps(project_dir: Path, steps: tuple[GuideStep, ...]) -> ProjectPlan:
    """Wrap validated mutations for an existing project."""
    if not project_dir.is_dir():
        raise GuidePlanError(f"Le projet n'existe pas : {project_dir}")
    if not steps:
        raise GuidePlanError("Le plan ne contient aucune étape.")
    return ProjectPlan(
        target_dir=project_dir,
        intent=None,
        steps=steps,
        creates_project=False,
    )


def plan_add_entity(entity: str, profile: str) -> GuideStep:
    _validate_component(entity, "entité")
    if profile not in {"minimal", "crud"}:
        raise GuidePlanError("Le profil doit être minimal ou crud.")
    return _entity_step(entity, profile=profile)


def plan_add_usecase(
    usecase: str,
    *,
    entity: str | None,
    new_entity: str | None,
    no_entity: bool,
) -> GuideStep:
    _validate_component(usecase, "cas d'usage")
    modes = sum(
        value is not None and value is not False
        for value in (entity, new_entity, no_entity)
    )
    if modes != 1:
        raise GuidePlanError(
            "Choisissez exactement une entité existante, une nouvelle entité ou un cas transverse."
        )
    if entity is not None:
        _validate_component(entity, "entité")
    if new_entity is not None:
        _validate_component(new_entity, "nouvelle entité")
    args = {
        "usecase": usecase,
        "entity": entity,
        "new_entity": new_entity,
        "no_entity": no_entity,
    }
    argv = ["add-usecase", usecase]
    if entity is not None:
        argv.extend(("--entity", entity))
    elif new_entity is not None:
        argv.extend(("--new-entity", new_entity))
    else:
        argv.append("--no-entity")
    return _step(f"Ajouter le cas d'usage {usecase}", "add-usecase", args, argv)


def plan_add_adapter(
    capability: str,
    adapter: str,
    *,
    params: dict[str, str],
    profile: str | None,
    secret_params: frozenset[str] = frozenset(),
) -> GuideStep:
    return _adapter_step(
        capability,
        adapter,
        params=params,
        profile=profile,
        secret_params=secret_params,
    )


def plan_expose_usecase(
    usecase: str,
    *,
    via: str,
    feature: str,
    public_name: str | None,
    http_path: str | None,
    method: str | None,
    status_code: int,
    command_type: str | None,
) -> GuideStep:
    _validate_component(usecase, "cas d'usage")
    _validate_component(feature, "feature")
    _validate_binding(via, http_path, method, status_code, command_type)
    args = {
        "usecase": usecase,
        "via": via,
        "feature": feature,
        "public_name": public_name,
        "http_path": http_path,
        "method": method,
        "status_code": status_code,
        "command_type": command_type,
    }
    argv = ["expose-usecase", usecase, "--via", via, "--feature", feature]
    if public_name is not None:
        argv.extend(("--name", public_name))
    if http_path is not None:
        argv.extend(("--path", http_path))
    if method is not None:
        argv.extend(("--method", method))
    if status_code != 200:
        argv.extend(("--status-code", str(status_code)))
    if command_type is not None:
        argv.extend(("--command-type", command_type))
    return _step(
        f"Exposer {usecase} via {via}",
        "expose-usecase",
        args,
        argv,
    )


def plan_expose_feature(feature: str, http_path: str) -> GuideStep:
    _validate_component(feature, "feature")
    _validate_http_path(http_path)
    return _step(
        f"Exposer la feature {feature} via FastAPI",
        "expose-feature",
        {"feature": feature, "via": "fastapi", "http_path": http_path},
        ("expose-feature", feature, "--via", "fastapi", "--path", http_path),
    )


def shell_command(step: GuideStep) -> str:
    return shlex.join(("arclith-cli", *step.argv))


def _validate_answers(answers: NewProjectAnswers) -> None:
    _validate_project_target(answers)
    if answers.entity is not None:
        _validate_component(answers.entity, "entité")
    if answers.intent != ProjectIntent.MINIMAL:
        _validate_complete_project_answers(answers)


def _validate_project_target(answers: NewProjectAnswers) -> None:
    if not answers.parent_dir.is_dir():
        raise GuidePlanError(
            f"Le répertoire parent n'existe pas : {answers.parent_dir}"
        )
    _validate_component(answers.project_name, "projet")
    if (answers.parent_dir / answers.project_name).exists():
        raise GuidePlanError(
            f"Le répertoire cible existe déjà : {answers.parent_dir / answers.project_name}"
        )


def _validate_complete_project_answers(answers: NewProjectAnswers) -> None:
    _validate_required_core_answers(answers)
    if answers.intent in {ProjectIntent.API_CRUD, ProjectIntent.API_CUSTOM}:
        _validate_http_answers(answers)
    if answers.intent == ProjectIntent.MCP:
        _validate_port(answers.transport_port, "MCP")


def _validate_required_core_answers(answers: NewProjectAnswers) -> None:
    if answers.entity is None:
        raise GuidePlanError("Une entité est requise pour ce parcours.")
    if answers.repository not in _SUPPORTED_REPOSITORIES:
        raise GuidePlanError("Un repository explicite est requis pour ce parcours.")
    if answers.intent != ProjectIntent.API_CRUD and answers.usecase is None:
        raise GuidePlanError("Un cas d'usage est requis pour ce parcours.")
    if answers.usecase is not None:
        _validate_component(answers.usecase, "cas d'usage")


def _validate_http_answers(answers: NewProjectAnswers) -> None:
    _validate_port(answers.transport_port, "HTTP")
    if answers.public_path is None:
        raise GuidePlanError("Un chemin HTTP est requis pour ce parcours.")
    _validate_http_path(answers.public_path)


def _validate_port(value: int | None, label: str) -> None:
    if value is None or not 1 <= value <= 65535:
        raise GuidePlanError(f"Le port {label} doit être compris entre 1 et 65535.")


def _validate_binding(
    via: str,
    http_path: str | None,
    method: str | None,
    status_code: int,
    command_type: str | None,
) -> None:
    if via not in {"fastapi", "fastmcp", "langgraph", "rabbitmq"}:
        raise GuidePlanError(f"Transport non supporté : {via}")
    if via == "fastapi":
        _validate_fastapi_binding(http_path, method)
    if not 200 <= status_code <= 299 or status_code in {204, 205}:
        raise GuidePlanError(
            "Le statut doit être un code 2xx avec un corps de réponse."
        )
    if via == "rabbitmq" and not command_type:
        raise GuidePlanError("Un type de commande versionné est requis pour RabbitMQ.")


def _validate_fastapi_binding(
    http_path: str | None,
    method: str | None,
) -> None:
    if http_path is None:
        raise GuidePlanError("Un chemin HTTP est requis pour FastAPI.")
    _validate_http_path(http_path)
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise GuidePlanError("Méthode HTTP invalide.")


def _validate_component(value: str, label: str) -> None:
    if not _COMPONENT_RE.fullmatch(value):
        raise GuidePlanError(
            f"Nom de {label} invalide : lettres, chiffres, _ et -, en commençant par une lettre."
        )


def _validate_http_path(value: str) -> None:
    if not value.startswith("/v1/") or any(
        character.isspace() or character in "?#\\" for character in value
    ):
        raise GuidePlanError(
            "Le chemin HTTP doit être absolu, sous /v1/, sans espace, query ni fragment."
        )


def _init_step(project_name: str, parent_dir: Path) -> GuideStep:
    return _step(
        f"Initialiser {project_name}",
        "init",
        {"project_name": project_name, "directory": "."},
        ("init", project_name, "--dir", str(parent_dir)),
    )


def _entity_step(entity: str, *, profile: str) -> GuideStep:
    args = {
        "entity": entity,
        "profile": profile,
        **application_profile_recipe_metadata(profile),
    }
    return _step(
        f"Ajouter l'entité {entity} ({profile})",
        "add-entity",
        args,
        ("add-entity", entity, "--profile", profile),
    )


def _usecase_step(usecase: str, entity: str) -> GuideStep:
    return plan_add_usecase(
        usecase,
        entity=entity,
        new_entity=None,
        no_entity=False,
    )


def _adapter_step(
    capability: str,
    adapter: str,
    *,
    params: dict[str, str],
    profile: str | None = None,
    secret_params: frozenset[str] = frozenset(),
) -> GuideStep:
    args = {
        "capability": capability,
        "adapter": adapter,
        "entities": [],
        "activate": True,
        "profile": profile,
        "params": params,
    }
    argv = [
        "add-adapter",
        "--capability",
        capability,
        "--adapter",
        adapter,
    ]
    if profile is not None:
        argv.extend(("--profile", profile))
    for name, value in sorted(params.items()):
        displayed_value = "<redacted>" if name in secret_params else value
        argv.extend(("--param", f"{name}={displayed_value}"))
    argv.append("--yes")
    return _step(
        f"Ajouter {capability}/{adapter}",
        "add-adapter",
        args,
        argv,
    )


def _feature_step(entity: str, http_path: str) -> GuideStep:
    return plan_expose_feature(EntityNames.from_input(entity).snake, http_path)


def _transport_step(answers: NewProjectAnswers) -> GuideStep:
    if answers.intent == ProjectIntent.API_CUSTOM:
        assert answers.transport_port is not None
        return _adapter_step(
            "api", "fastapi", params={"port": str(answers.transport_port)}
        )
    if answers.intent == ProjectIntent.MCP:
        assert answers.transport_port is not None
        return _adapter_step(
            "mcp", "fastmcp", params={"port": str(answers.transport_port)}
        )
    if answers.intent == ProjectIntent.AGENT:
        assert answers.entity is not None
        return _adapter_step(
            "agent",
            "langgraph",
            params={"graph_name": EntityNames.from_input(answers.entity).snake},
        )
    return _adapter_step("command-bus", "rabbitmq", params={})


def _binding_step(answers: NewProjectAnswers) -> GuideStep:
    assert answers.entity is not None
    assert answers.usecase is not None
    feature = EntityNames.from_input(answers.entity).snake
    if answers.intent == ProjectIntent.API_CUSTOM:
        assert answers.public_path is not None
        return plan_expose_usecase(
            answers.usecase,
            via="fastapi",
            feature=feature,
            public_name=None,
            http_path=answers.public_path,
            method="POST",
            status_code=201,
            command_type=None,
        )
    if answers.intent == ProjectIntent.MCP:
        return plan_expose_usecase(
            answers.usecase,
            via="fastmcp",
            feature=feature,
            public_name=None,
            http_path=None,
            method=None,
            status_code=200,
            command_type=None,
        )
    if answers.intent == ProjectIntent.AGENT:
        return plan_expose_usecase(
            answers.usecase,
            via="langgraph",
            feature=feature,
            public_name=None,
            http_path=None,
            method=None,
            status_code=200,
            command_type=None,
        )
    return plan_expose_usecase(
        answers.usecase,
        via="rabbitmq",
        feature=feature,
        public_name=None,
        http_path=None,
        method=None,
        status_code=200,
        command_type=f"{feature}.{EntityNames.from_input(answers.usecase).snake}.v1",
    )


def _step(
    title: str,
    command: str,
    args: Mapping[str, object],
    argv: list[str] | tuple[str, ...],
) -> GuideStep:
    return GuideStep(
        title=title,
        command=command,
        args=dict(args),
        argv=tuple(argv),
    )
