from pathlib import Path
from typing import Any

from arclith_cli.application_blueprints import (
    application_blueprint_digest,
    application_parameters_digest,
    canonical_blueprint_parameters,
    get_application_blueprint,
)
from arclith_cli.blueprint_generation import (
    add_application_blueprint_cmd,
    create_entity_with_application_blueprint,
    plan_application_profile_for_new_entity,
)
from arclith_cli.core_scaffold import add_entity_cmd
from arclith_cli.project_paths import detect_project_paths
from arclith_cli.recipe_models import RecipeError
from arclith_cli.state_machine_entity import render_state_machine_entity
from arclith_cli.state_machine_spec import StateMachineSpec


def replay_application_blueprint_step(
    command: str,
    target_dir: Path,
    args: dict[str, Any],
) -> None:
    """Replay entity and application-blueprint recipe operations."""
    if command == "add-entity":
        replay_add_entity_step(target_dir, args)
        return
    if command == "add-blueprint":
        replay_add_blueprint_step(target_dir, args)
        return
    raise ValueError(f"Unsupported application blueprint recipe command: {command}")


def replay_add_entity_step(target_dir: Path, args: dict[str, Any]) -> None:
    """Replay entity creation, including an optional application profile."""
    entity = str(args["entity"])
    profile = str(args.get("profile", "minimal"))
    validate_application_recipe_metadata(profile, args)
    raw_parameters = args.get("parameters")
    parameters = raw_parameters if isinstance(raw_parameters, dict) else None
    blueprint_plan = plan_application_profile_for_new_entity(
        target_dir,
        profile_name=profile,
        entity_name=entity,
        parameters=parameters,
    )
    entity_content = None
    if blueprint_plan is not None and blueprint_plan.blueprint.name == "state-machine":
        entity_content = render_state_machine_entity(
            detect_project_paths(target_dir),
            blueprint_plan.entity,
            StateMachineSpec.from_parameters(blueprint_plan.parameters),
        )
    if blueprint_plan is not None:
        create_entity_with_application_blueprint(
            blueprint_plan,
            entity_name=entity,
            entity_content=entity_content,
        )
    else:
        add_entity_cmd(project_dir=target_dir, entity_name=entity)


def replay_add_blueprint_step(target_dir: Path, args: dict[str, Any]) -> None:
    """Replay a standalone application-blueprint decision."""
    feature = args.get("feature")
    blueprint_name = required_recipe_blueprint_name(args)
    validate_application_recipe_metadata(blueprint_name, args)
    raw_parameters = args.get("parameters")
    parameters = raw_parameters if isinstance(raw_parameters, dict) else None
    add_application_blueprint_cmd(
        project_dir=target_dir,
        blueprint_name=blueprint_name,
        entity_name=str(args["entity"]),
        feature_name=str(feature) if feature else None,
        dry_run=False,
        parameters=parameters,
    )


def required_recipe_blueprint_name(args: dict[str, Any]) -> str:
    """Return a statically valid blueprint name from recorded recipe metadata."""

    blueprint_name = args.get("blueprint")
    if not isinstance(blueprint_name, str) or not blueprint_name.strip():
        raise RecipeError(
            "Recipe add-blueprint step requires a non-empty string 'blueprint'"
        )
    return blueprint_name


def validate_application_recipe_metadata(
    blueprint_name: str,
    args: dict[str, Any],
) -> None:
    """Reject recorded template or parameter drift before replay writes."""

    if blueprint_name == "minimal":
        blueprint_metadata = {
            "blueprint",
            "blueprint_version",
            "operations",
            "parameters",
            "parameters_digest",
            "template_digest",
        } & args.keys()
        if blueprint_metadata:
            raise RecipeError(
                "Minimal application profile cannot include blueprint metadata: "
                + ", ".join(sorted(blueprint_metadata))
            )
        return
    try:
        blueprint = get_application_blueprint(blueprint_name)
    except ValueError as exc:
        raise RecipeError(
            f"Recipe references an invalid blueprint {blueprint_name!r}: {exc}"
        ) from exc
    recorded_template = args.get("template_digest")
    recorded_parameters = args.get("parameters_digest")
    required_parameterized_metadata = {
        "blueprint_version",
        "operations",
        "parameters_digest",
        "template_digest",
    }
    missing_metadata = {
        key
        for key in required_parameterized_metadata
        if key not in args or args[key] is None
    }
    if blueprint.parameterized and missing_metadata:
        raise RecipeError(
            f"Parameterized blueprint {blueprint.name!r} replay requires complete "
            "metadata: " + ", ".join(sorted(required_parameterized_metadata))
        )
    raw_parameters = args.get("parameters")
    try:
        parameters = canonical_blueprint_parameters(blueprint, raw_parameters)
    except ValueError as exc:
        raise RecipeError(
            f"Blueprint {blueprint.name!r} has invalid recorded parameters: {exc}"
        ) from exc
    expected_operations = blueprint.operations
    if blueprint.parameterized:
        expected_operations = StateMachineSpec.from_parameters(parameters).operations
    recorded_version = args.get("blueprint_version")
    if "blueprint_version" in args and (
        type(recorded_version) is not int or recorded_version != blueprint.version
    ):
        raise RecipeError(
            f"Blueprint {blueprint.name!r} version drift: recorded "
            f"{recorded_version!r}, current {blueprint.version!r}"
        )
    recorded_operations = args.get("operations")
    if "operations" in args and recorded_operations != list(expected_operations):
        raise RecipeError(
            f"Blueprint {blueprint.name!r} operations drift: recorded "
            f"{recorded_operations!r}, current {list(expected_operations)!r}"
        )
    expected_template = application_blueprint_digest(blueprint)
    if recorded_template is not None and recorded_template != expected_template:
        raise RecipeError(
            f"Blueprint {blueprint.name!r} template digest drift: "
            f"recorded {recorded_template!r}, current {expected_template!r}"
        )
    expected_parameters = application_parameters_digest(blueprint, parameters)
    if recorded_parameters is not None and recorded_parameters != expected_parameters:
        raise RecipeError(
            f"Blueprint {blueprint.name!r} parameters digest drift: "
            f"recorded {recorded_parameters!r}, current {expected_parameters!r}"
        )
