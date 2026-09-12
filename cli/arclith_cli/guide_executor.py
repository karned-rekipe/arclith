from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping

from arclith_cli.add_adapter import add_adapter_cmd
from arclith_cli.adapter_blueprints import blueprint_digest, get_adapter_blueprint
from arclith_cli.application_blueprint_recipe import (
    replay_application_blueprint_step,
)
from arclith_cli.core_scaffold import add_usecase_cmd
from arclith_cli.feature_projection import (
    FEATURE_PROJECTION_VERSION,
    apply_feature_projection,
    feature_projection_digest,
    plan_feature_projection,
)
from arclith_cli.guide_models import (
    GuidePlanError,
    GuideStep,
    ProjectExecutionResult,
    ProjectPlan,
)
from arclith_cli.init_project import init_project_cmd
from arclith_cli.recipe import (
    adapter_secret_metadata,
    record_successful_step,
    replay_recipe,
    snapshot_project_files,
)
from arclith_cli.recipe_models import Recipe, RecipeSecretRef
from arclith_cli.usecase_binding import apply_binding, plan_binding

StepProgress = Callable[[int, int, GuideStep], None]


@dataclass(frozen=True)
class _ExecutedStep:
    args: Mapping[str, Any]
    secret_fields: Mapping[str, str]
    secret_references: tuple[RecipeSecretRef, ...]


def execute_project_plan(
    plan: ProjectPlan,
    *,
    on_step: StepProgress | None = None,
) -> ProjectExecutionResult:
    """Execute a confirmed guide plan and record every successful decision."""
    if plan.creates_project:
        return _execute_new_project_plan(plan, on_step=on_step)
    if not plan.target_dir.is_dir():
        raise GuidePlanError(f"Le projet n'existe pas : {plan.target_dir}")
    return _execute_steps(plan, plan.target_dir.resolve(), on_step=on_step)


def replay_recipe_atomically(
    recipe: Recipe,
    *,
    target_dir: Path,
) -> tuple[str, ...]:
    """Replay a complete recipe without exposing a partially created target."""
    target = target_dir.resolve()
    if target.exists():
        raise GuidePlanError(f"Le répertoire cible existe déjà : {target}")
    if not target.parent.is_dir():
        raise GuidePlanError(f"Le répertoire parent n'existe pas : {target.parent}")
    prefix = f".{target.name}.arclith-replay-"
    with TemporaryDirectory(prefix=prefix, dir=target.parent) as temporary:
        staged_dir = Path(temporary) / target.name
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            executed = replay_recipe(
                recipe,
                recipe.steps,
                target_dir=staged_dir,
                strict=True,
            )
        staged_dir.replace(target)
    return executed


def _execute_new_project_plan(
    plan: ProjectPlan,
    *,
    on_step: StepProgress | None,
) -> ProjectExecutionResult:
    target_dir = plan.target_dir.resolve()
    parent_dir = target_dir.parent
    if not parent_dir.is_dir():
        raise GuidePlanError(f"Le répertoire parent n'existe pas : {parent_dir}")
    if target_dir.exists():
        raise GuidePlanError(f"Le répertoire cible existe déjà : {target_dir}")
    if not plan.steps or plan.steps[0].command != "init":
        raise GuidePlanError("Un nouveau projet doit commencer par l'étape init.")

    prefix = f".{target_dir.name}.arclith-"
    with TemporaryDirectory(prefix=prefix, dir=parent_dir) as temporary:
        staged_dir = Path(temporary) / target_dir.name
        staged_plan = ProjectPlan(
            target_dir=staged_dir,
            intent=plan.intent,
            steps=plan.steps,
            creates_project=True,
        )
        result = _execute_steps(staged_plan, staged_dir, on_step=on_step)
        staged_dir.replace(target_dir)
    return ProjectExecutionResult(
        root=target_dir,
        executed_commands=result.executed_commands,
    )


def _execute_steps(
    plan: ProjectPlan,
    project_dir: Path,
    *,
    on_step: StepProgress | None,
) -> ProjectExecutionResult:
    executed: list[str] = []
    total = len(plan.steps)
    for index, step in enumerate(plan.steps, start=1):
        if on_step is not None:
            on_step(index, total, step)
        before = snapshot_project_files(project_dir)
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            metadata = _execute_step(step, project_dir)
        record_successful_step(
            project_dir,
            command=step.command,
            args=metadata.args,
            before=before,
            secret_fields=metadata.secret_fields,
            secret_references=metadata.secret_references,
        )
        executed.append(step.command)
    return ProjectExecutionResult(
        root=project_dir,
        executed_commands=tuple(executed),
    )


def _execute_step(step: GuideStep, project_dir: Path) -> _ExecutedStep:
    if step.command == "init":
        return _execute_init(step, project_dir)
    if not project_dir.is_dir():
        raise GuidePlanError(
            f"Le projet n'existe pas avant l'étape {step.command} : {project_dir}"
        )
    executor = _PROJECT_STEP_EXECUTORS.get(step.command)
    if executor is None:
        raise GuidePlanError(f"Commande du guide non supportée : {step.command}")
    return executor(step, project_dir)


def _execute_init(step: GuideStep, project_dir: Path) -> _ExecutedStep:
    init_project_cmd(
        project_name=str(step.args.get("project_name") or project_dir.name),
        directory=project_dir.parent,
        target_path=project_dir,
    )
    return _metadata(step.args)


def _execute_entity(step: GuideStep, project_dir: Path) -> _ExecutedStep:
    replay_application_blueprint_step(step.command, project_dir, step.args)
    return _metadata(step.args)


def _execute_usecase(step: GuideStep, project_dir: Path) -> _ExecutedStep:
    raw_entity = step.args.get("entity")
    raw_new_entity = step.args.get("new_entity")
    add_usecase_cmd(
        project_dir=project_dir,
        usecase_name=str(step.args["usecase"]),
        entity_name=str(raw_entity) if raw_entity is not None else None,
        new_entity_name=str(raw_new_entity) if raw_new_entity is not None else None,
    )
    return _metadata(step.args)


def _execute_binding(step: GuideStep, project_dir: Path) -> _ExecutedStep:
    binding = plan_binding(project_dir, **step.args)
    apply_binding(binding)
    return _metadata(step.args)


def _execute_feature(step: GuideStep, project_dir: Path) -> _ExecutedStep:
    projection = plan_feature_projection(
        project_dir,
        feature_name=str(step.args["feature"]),
        via=str(step.args["via"]),
        http_path=str(step.args["http_path"]),
    )
    apply_feature_projection(projection)
    args = {
        "feature": projection.feature.feature,
        "via": projection.via,
        "http_path": projection.http_path,
        "blueprint": projection.feature.blueprint.name,
        "blueprint_version": projection.feature.blueprint.version,
        "operations": list(projection.feature.operations),
        "projection_version": FEATURE_PROJECTION_VERSION,
        "template_digest": feature_projection_digest(projection),
    }
    return _metadata(args)


def _execute_adapter(step: GuideStep, project_dir: Path) -> _ExecutedStep:
    raw_params = step.args.get("params") or {}
    raw_entities = step.args.get("entities") or []
    if not isinstance(raw_params, dict):
        raise GuidePlanError("Les paramètres d'adapter doivent former un mapping.")
    if not isinstance(raw_entities, list):
        raise GuidePlanError("Les entités d'adapter doivent former une liste.")
    result = add_adapter_cmd(
        project_dir=project_dir,
        capability_name=str(step.args["capability"]),
        adapter=str(step.args["adapter"]),
        entity_names=[str(item) for item in raw_entities] or None,
        activate=bool(step.args.get("activate", True)),
        adapter_params={str(key): str(value) for key, value in raw_params.items()},
        profile=(
            str(step.args["profile"]) if step.args.get("profile") is not None else None
        ),
        yes=True,
    )
    blueprint = get_adapter_blueprint(result.adapter)
    secret_fields, secret_references = adapter_secret_metadata(result.adapter)
    args = {
        "capability": result.capability.name,
        "adapter": result.adapter.name,
        "entities": [entity.pascal for entity in result.entities],
        "activate": result.activate,
        "profile": result.profile,
        "params": result.params,
        "blueprint_version": blueprint.version,
        "template_digest": blueprint_digest(blueprint),
    }
    return _ExecutedStep(
        args=args,
        secret_fields=secret_fields,
        secret_references=secret_references,
    )


def _metadata(args: Mapping[str, Any]) -> _ExecutedStep:
    return _ExecutedStep(args=args, secret_fields={}, secret_references=())


_PROJECT_STEP_EXECUTORS = {
    "add-entity": _execute_entity,
    "add-usecase": _execute_usecase,
    "add-adapter": _execute_adapter,
    "expose-usecase": _execute_binding,
    "expose-feature": _execute_feature,
}
