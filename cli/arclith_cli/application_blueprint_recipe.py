from pathlib import Path
from typing import Any

from arclith_cli.blueprint_generation import (
    add_application_blueprint_cmd,
    apply_application_blueprint,
    plan_application_profile_for_new_entity,
)
from arclith_cli.core_scaffold import add_entity_cmd


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
    blueprint_plan = plan_application_profile_for_new_entity(
        target_dir,
        profile_name=profile,
        entity_name=entity,
    )
    add_entity_cmd(project_dir=target_dir, entity_name=entity)
    if blueprint_plan is not None:
        apply_application_blueprint(blueprint_plan)


def replay_add_blueprint_step(target_dir: Path, args: dict[str, Any]) -> None:
    """Replay a standalone application-blueprint decision."""
    feature = args.get("feature")
    add_application_blueprint_cmd(
        project_dir=target_dir,
        blueprint_name=str(args["blueprint"]),
        entity_name=str(args["entity"]),
        feature_name=str(feature) if feature else None,
        dry_run=False,
    )
