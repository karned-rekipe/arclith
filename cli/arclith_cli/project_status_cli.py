import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from arclith_cli.guide_models import GuidePlanError, ProjectOverview
from arclith_cli.guide_rendering import GuideRenderer
from arclith_cli.guide_status import find_project_root, inspect_project

console = Console()


def status_command(
    directory: Annotated[
        Path,
        typer.Option("--dir", "-d", help="Racine du projet Arclith."),
    ] = Path("."),
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Afficher un état machine-readable."),
    ] = False,
) -> None:
    """Afficher l'état réel du projet courant."""
    overview = _load_overview(directory)
    if as_json:
        typer.echo(
            json.dumps(_overview_as_dict(overview), ensure_ascii=False, indent=2)
        )
        return
    GuideRenderer(console).overview(overview)


def doctor_command(
    directory: Annotated[
        Path,
        typer.Option("--dir", "-d", help="Racine du projet Arclith."),
    ] = Path("."),
) -> None:
    """Vérifier la lisibilité de la structure, des manifestes et de la recette."""
    overview = _load_overview(directory)
    GuideRenderer(console).overview(overview)
    if overview.issues:
        raise typer.Exit(1)
    console.print(
        "[bold green]✓ Structure, manifestes et recette sont lisibles.[/bold green]"
    )


def _load_overview(directory: Path) -> ProjectOverview:
    try:
        root = find_project_root(directory)
        if root is None:
            raise GuidePlanError(f"Projet Arclith introuvable : {directory.resolve()}")
        return inspect_project(root)
    except (GuidePlanError, OSError, ValueError) as exc:
        console.print(f"[bold red]✗ {exc}[/bold red]")
        raise typer.Exit(1) from exc


def _overview_as_dict(overview: ProjectOverview) -> dict[str, object]:
    return {
        "root": str(overview.root),
        "name": overview.name,
        "package": overview.package,
        "entities": list(overview.entities),
        "usecases": list(overview.usecases),
        "features": [
            {
                "name": feature.name,
                "entity": feature.entity,
                "blueprint": feature.blueprint,
            }
            for feature in overview.features
        ],
        "adapters": list(overview.adapters),
        "issues": list(overview.issues),
    }
