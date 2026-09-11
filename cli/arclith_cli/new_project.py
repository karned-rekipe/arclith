from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from arclith_cli.application_blueprints import get_application_blueprint
from arclith_cli.blueprint_generation import add_application_blueprint_cmd
from arclith_cli.core_scaffold import add_entity_cmd
from arclith_cli.init_project import init_project_cmd
from arclith_cli.rename import EntityNames

console = Console()


def new_project_cmd(
    *,
    entity: str,
    project_name: str,
    directory: Path,
    port: int,
    repo_ref: str,
    template_dir: Path | None,
    profile: str = "minimal",
    target_path: Path | None = None,
) -> Path:
    """Create the canonical minimal project and its first entity.

    ``new`` is kept as a compatibility shortcut for ``init`` followed by
    ``add-entity``. It deliberately installs no adapter: transports, drivers,
    and runtime files remain explicit ``add-adapter`` decisions.
    """
    _validate_suggested_api_port(port)
    if profile != "minimal":
        get_application_blueprint(profile)
    _ = repo_ref, template_dir  # Retained for replay compatibility with old recipes.
    entity_names = EntityNames.from_input(entity)

    target_dir = init_project_cmd(
        project_name=project_name,
        directory=directory,
        target_path=target_path,
    )
    add_entity_cmd(project_dir=target_dir, entity_name=entity)
    if profile != "minimal":
        add_application_blueprint_cmd(
            project_dir=target_dir,
            blueprint_name=profile,
            entity_name=entity,
            feature_name=None,
            dry_run=False,
        )

    application_next = (
        f"[bold cyan]arclith-cli add-usecase Create{entity_names.pascal} "
        f"--entity {entity_names.pascal}[/bold cyan]"
        if profile == "minimal"
        else "[bold cyan]Compléter les commandes et invariants du CRUD généré[/bold cyan]"
    )

    console.print(
        Panel(
            "Aucun adapter n'a été ajouté automatiquement.\n\n"
            f"{application_next}\n"
            "[bold cyan]arclith-cli add-adapter[/bold cyan]"
            "  [dim]# choisir explicitement repository, API, MCP, bus…[/dim]\n"
            "[bold cyan]arclith-cli add-adapter --capability api --adapter fastapi "
            f"--param port={port} --yes[/bold cyan]",
            title="[bold blue]Suite explicite[/bold blue]",
            border_style="green",
        )
    )
    return target_dir


def _validate_suggested_api_port(port: int) -> None:
    if 0 < port <= 65535:
        return
    console.print(
        f"[red]✗[/red] Port REST invalide: [bold]{port}[/bold]. "
        "Utilisez une valeur entre 1 et 65535."
    )
    raise typer.Exit(1)
