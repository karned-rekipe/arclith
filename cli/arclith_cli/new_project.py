from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import typer
from rich.console import Console
from rich.panel import Panel

from arclith_cli.blueprint_generation import (
    apply_application_blueprint,
    plan_application_profile_for_new_entity,
)
from arclith_cli.core_scaffold import add_entity_cmd
from arclith_cli.init_project import (
    init_project_cmd,
    initial_project_initializer_paths,
    project_paths_for_new_project,
)
from arclith_cli.rename import EntityNames
from arclith_cli.state_machine_entity import render_state_machine_entity
from arclith_cli.state_machine_spec import StateMachineSpec

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
    parameters: Mapping[str, Any] | None = None,
    target_path: Path | None = None,
) -> Path:
    """Create the canonical minimal project and its first entity.

    ``new`` is kept as a compatibility shortcut for ``init`` followed by
    ``add-entity``. It deliberately installs no adapter: transports, drivers,
    and runtime files remain explicit ``add-adapter`` decisions.
    """
    _validate_suggested_api_port(port)
    _ = repo_ref, template_dir  # Retained for replay compatibility with old recipes.
    entity_names = EntityNames.from_input(entity)
    planned_paths = project_paths_for_new_project(
        project_name=project_name,
        directory=directory,
        target_path=target_path,
    )
    blueprint_plan = plan_application_profile_for_new_entity(
        planned_paths.root,
        profile_name=profile,
        entity_name=entity,
        parameters=parameters,
        project_paths=planned_paths,
        expected_empty_initializers=initial_project_initializer_paths(planned_paths),
    )
    entity_content = None
    if blueprint_plan is not None and blueprint_plan.blueprint.name == "state-machine":
        entity_content = render_state_machine_entity(
            planned_paths,
            blueprint_plan.entity,
            StateMachineSpec.from_parameters(blueprint_plan.parameters),
        )
    target_dir = init_project_cmd(
        project_name=project_name,
        directory=directory,
        target_path=target_path,
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

    application_next = (
        f"[bold cyan]arclith-cli add-usecase Create{entity_names.pascal} "
        f"--entity {entity_names.pascal}[/bold cyan]"
        if profile == "minimal"
        else (
            "[bold cyan]Compléter les champs et invariants du blueprint "
            f"{profile} généré[/bold cyan]"
        )
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
