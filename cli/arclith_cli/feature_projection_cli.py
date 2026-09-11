"""CLI entrypoint for explicit application-feature projections."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from arclith_cli.feature_projection import (
    FEATURE_PROJECTION_VERSION,
    apply_feature_projection,
    feature_projection_digest,
    plan_feature_projection,
)
from arclith_cli.recipe import record_successful_step, snapshot_project_files

console = Console()


def expose_feature_command(
    feature: Annotated[
        str,
        typer.Argument(help="Feature applicative déclarée sous .arclith/features."),
    ],
    via: Annotated[
        str,
        typer.Option("--via", help="Transport cible ; fastapi dans cette version."),
    ],
    http_path: Annotated[
        str | None,
        typer.Option(
            "--path",
            help=(
                "Chemin de collection REST ; défaut déterministe : "
                "/v1/<feature-en-kebab-case>."
            ),
        ),
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    no_record: Annotated[bool, typer.Option("--no-record", hidden=True)] = False,
) -> None:
    """Projeter explicitement une feature applicative vers un adapter installé."""
    root = Path.cwd()
    try:
        plan = plan_feature_projection(
            root,
            feature_name=feature,
            via=via,
            http_path=http_path,
        )
        for path in plan.binding_plan.files:
            action = "update" if path.exists() else "create"
            console.print(f"{action} {path.relative_to(root)}")
        for path in plan.binding_plan.preserved:
            console.print(f"preserve {path.relative_to(root)}")
        if dry_run:
            console.print("Dry-run: no files or recipe changed.")
            return
        before = snapshot_project_files(root) if not no_record else {}
        changed = apply_feature_projection(plan)
        if changed and not no_record:
            record_successful_step(
                root,
                command="expose-feature",
                args={
                    "feature": plan.feature.feature,
                    "via": plan.via,
                    "http_path": plan.http_path,
                    "blueprint": plan.feature.blueprint.name,
                    "blueprint_version": plan.feature.blueprint.version,
                    "operations": list(plan.feature.operations),
                    "projection_version": FEATURE_PROJECTION_VERSION,
                    "template_digest": feature_projection_digest(plan),
                },
                before=before,
            )
        console.print(
            f"Feature projection ready ({len(changed)} changed files): "
            f"{plan.via} {plan.http_path}."
        )
    except (ValueError, SyntaxError, OSError) as exc:
        console.print(f"[red]Feature projection rejected:[/red] {exc}")
        raise typer.Exit(1) from exc
