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
    apply_application_blueprint,
    plan_application_profile_for_new_entity,
)
from arclith_cli.core_scaffold import add_entity_cmd
from arclith_cli.project_paths import detect_project_paths
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
    add_entity_cmd(
        project_dir=target_dir,
        entity_name=entity,
        model_base=(
            blueprint_plan.entity.model_base if blueprint_plan is not None else "entity"
        ),
        entity_content=entity_content,
    )
    if blueprint_plan is not None:
        apply_application_blueprint(blueprint_plan)


def replay_add_blueprint_step(target_dir: Path, args: dict[str, Any]) -> None:
    """Replay a standalone application-blueprint decision."""
    feature = args.get("feature")
    blueprint_name = str(args["blueprint"])
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


def validate_application_recipe_metadata(
    blueprint_name: str,
    args: dict[str, Any],
) -> None:
    """Reject recorded template or parameter drift before replay writes."""

    if blueprint_name == "minimal":
        return
    blueprint = get_application_blueprint(blueprint_name)
    raw_parameters = args.get("parameters")
    parameters = canonical_blueprint_parameters(blueprint, raw_parameters)
    recorded_template = args.get("template_digest")
    expected_template = application_blueprint_digest(blueprint)
    if recorded_template is not None and recorded_template != expected_template:
        raise ValueError(
            f"Blueprint {blueprint.name!r} template digest drift: "
            f"recorded {recorded_template!r}, current {expected_template!r}"
        )
    recorded_parameters = args.get("parameters_digest")
    expected_parameters = application_parameters_digest(blueprint, parameters)
    if recorded_parameters is not None and recorded_parameters != expected_parameters:
        raise ValueError(
            f"Blueprint {blueprint.name!r} parameters digest drift: "
            f"recorded {recorded_parameters!r}, current {expected_parameters!r}"
        )
