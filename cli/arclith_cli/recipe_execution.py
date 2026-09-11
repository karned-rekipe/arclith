"""Replay helpers for adapter and public-binding recipe steps."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from arclith_cli.recipe_models import RecipeError, RecipeStep


def execute_adapter_step(
    step: RecipeStep,
    target_dir: Path,
    args: dict[str, Any],
) -> None:
    """Replay a validated adapter step without recording it again."""
    from arclith_cli.add_adapter import add_adapter_cmd

    raw_params = args.get("params") or {}
    if not isinstance(raw_params, dict):
        raise RecipeError(f"Step {step.id} add-adapter params must be a mapping.")
    raw_entities = args.get("entities") or []
    if not isinstance(raw_entities, list):
        raise RecipeError(f"Step {step.id} add-adapter entities must be a list.")
    add_adapter_cmd(
        project_dir=target_dir,
        capability_name=str(args.get("capability", "repository")),
        adapter=str(args["adapter"]),
        entity_names=[str(item) for item in raw_entities] or None,
        activate=bool(args.get("activate", True)),
        adapter_params=dict(raw_params),
        yes=True,
    )


def execute_binding_step(
    command: str,
    target_dir: Path,
    args: dict[str, Any],
) -> None:
    """Replay one isolated use-case or feature-level binding decision."""
    if command == "expose-usecase":
        from arclith_cli.usecase_binding import apply_binding, plan_binding

        apply_binding(plan_binding(target_dir, **args))
        return
    from arclith_cli.feature_projection import add_feature_projection_cmd

    add_feature_projection_cmd(
        target_dir,
        feature_name=str(args["feature"]),
        via=str(args["via"]),
        http_path=str(args["http_path"]),
        dry_run=False,
    )
