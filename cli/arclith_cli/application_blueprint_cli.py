import json
import re
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from arclith_cli.application_blueprints import (
    APPLICATION_BLUEPRINT_CATALOG,
    application_blueprint_catalog_as_dict,
    application_blueprint_digest,
    get_application_blueprint,
)
from arclith_cli.blueprint_generation import (
    add_application_blueprint_cmd,
    apply_application_blueprint,
    plan_application_blueprint_for_entity,
)
from arclith_cli.command_recording import record_success
from arclith_cli.core_scaffold import add_entity_cmd
from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.project_paths import detect_project_paths
from arclith_cli.recipe import snapshot_project_files
from arclith_cli.rename import EntityNames

console = Console()
_ENTITY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")


def add_entity_command(
    entity: Annotated[
        str | None,
        typer.Argument(
            help="Nom de l'entité métier au singulier. Exemple : Recipe, recipe_step, meal-plan",
        ),
    ] = None,
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            help="Profil applicatif initial : minimal ou un blueprint tel que crud.",
        ),
    ] = None,
    no_record: Annotated[
        bool,
        typer.Option("--no-record", hidden=True),
    ] = False,
) -> None:
    """Créer une entité minimale, avec un blueprint applicatif explicite en option."""
    interactive = entity is None
    resolved_name = entity or prompt_entity()
    try:
        resolved_profile = resolve_entity_profile(profile, interactive=interactive)
    except ValueError as exc:
        console.print(f"[red]✗ Profil invalide :[/red] {exc}")
        raise typer.Exit(1) from exc
    project_dir = Path.cwd()
    before = snapshot_project_files(project_dir) if not no_record else {}
    blueprint_plan = None
    if resolved_profile != "minimal":
        try:
            paths = detect_project_paths(project_dir)
            names = EntityNames.from_input(resolved_name)
            blueprint_plan = plan_application_blueprint_for_entity(
                project_dir,
                blueprint=get_application_blueprint(resolved_profile),
                entity=EntityInfo(
                    pascal=names.pascal,
                    snake=names.snake,
                    file_path=paths.domain_models / f"{names.snake}.py",
                ),
                feature_name=names.snake,
            )
        except (OSError, SyntaxError, ValueError) as exc:
            console.print(f"[red]✗ Blueprint refusé :[/red] {exc}")
            raise typer.Exit(1) from exc
    add_entity_cmd(project_dir=project_dir, entity_name=resolved_name)
    if blueprint_plan is not None:
        try:
            apply_application_blueprint(blueprint_plan)
        except (OSError, ValueError) as exc:
            console.print(f"[red]✗ Blueprint refusé :[/red] {exc}")
            raise typer.Exit(1) from exc
        console.print(
            f"[bold green]✓ Blueprint {resolved_profile} appliqué à "
            f"{blueprint_plan.entity.pascal}.[/bold green]"
        )
    if not no_record:
        record_success(
            project_dir,
            command="add-entity",
            args={
                "entity": resolved_name,
                "profile": resolved_profile,
                **application_profile_recipe_metadata(resolved_profile),
            },
            before=before,
        )


def blueprints_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Afficher le catalogue au format JSON."),
    ] = False,
) -> None:
    """Lister les blueprints applicatifs, distincts des adapters techniques."""
    if as_json:
        typer.echo(json.dumps(application_blueprint_catalog_as_dict(), indent=2))
        return

    table = Table(show_header=True, header_style="bold blue", box=None, padding=(0, 2))
    table.add_column("Blueprint")
    table.add_column("Version")
    table.add_column("Opérations")
    table.add_column("Description")
    for blueprint_spec in APPLICATION_BLUEPRINT_CATALOG:
        table.add_row(
            blueprint_spec.name,
            str(blueprint_spec.version),
            ", ".join(blueprint_spec.operations),
            blueprint_spec.description,
        )
    console.print(table)


def add_blueprint_command(
    blueprint: Annotated[
        str,
        typer.Argument(help="Blueprint applicatif à appliquer, par exemple crud."),
    ],
    entity: Annotated[
        str,
        typer.Option("--entity", "-e", help="Entité métier existante ciblée."),
    ],
    feature: Annotated[
        str | None,
        typer.Option(
            "--feature",
            help="Nom stable de la feature ; défaut : nom snake_case de l'entité.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Afficher le plan sans écrire de fichier."),
    ] = False,
    no_record: Annotated[
        bool,
        typer.Option("--no-record", hidden=True),
    ] = False,
) -> None:
    """Appliquer un blueprint au cœur applicatif sans installer d'adapter."""
    project_dir = Path.cwd()
    before = (
        snapshot_project_files(project_dir) if not no_record and not dry_run else {}
    )
    try:
        result = add_application_blueprint_cmd(
            project_dir=project_dir,
            blueprint_name=blueprint,
            entity_name=entity,
            feature_name=feature,
            dry_run=dry_run,
        )
    except (OSError, SyntaxError, ValueError) as exc:
        console.print(f"[red]✗ Blueprint refusé :[/red] {exc}")
        raise typer.Exit(1) from exc
    if not no_record and not dry_run and result.changed:
        record_success(
            project_dir,
            command="add-blueprint",
            args={
                "blueprint": result.blueprint.name,
                "entity": result.entity.pascal,
                "feature": result.feature,
                "operations": list(result.blueprint.operations),
                "blueprint_version": result.blueprint.version,
                "template_digest": application_blueprint_digest(result.blueprint),
            },
            before=before,
        )


def prompt_entity() -> str:
    console.print(
        "\n[bold]Entité[/bold] — utilisez le [yellow]singulier[/yellow] "
        "[dim](ex : Recipe, recipe_step, MealPlan)[/dim]"
    )
    while True:
        value = Prompt.ask("  [bold green]Nom de l'entité[/bold green]").strip()
        if not value:
            console.print("  [red]Le nom ne peut pas être vide.[/red]")
        elif not _ENTITY_RE.match(value):
            console.print(
                "  [red]Caractères invalides.[/red] "
                "[dim]Lettres, chiffres, _ et - uniquement. Doit commencer par une lettre.[/dim]"
            )
        else:
            return value


def resolve_entity_profile(value: str | None, *, interactive: bool) -> str:
    if value is None and not interactive:
        return "minimal"
    if value is None:
        labels = ["minimal", *(item.name for item in APPLICATION_BLUEPRINT_CATALOG)]
        console.print("\n[bold]Profil applicatif initial[/bold]")
        for index, label in enumerate(labels, start=1):
            console.print(f"  [cyan]{index}[/cyan]. {label}")
        selected = Prompt.ask(
            "  [bold green]Choix[/bold green]",
            choices=[str(index) for index in range(1, len(labels) + 1)],
            default="1",
        )
        return labels[int(selected) - 1]
    normalized = value.strip().lower()
    if normalized == "minimal":
        return normalized
    return get_application_blueprint(normalized).name


def application_profile_recipe_metadata(profile: str) -> dict[str, object]:
    """Describe a non-minimal profile well enough to audit recipe drift."""
    if profile == "minimal":
        return {}
    blueprint = get_application_blueprint(profile)
    return {
        "operations": list(blueprint.operations),
        "blueprint_version": blueprint.version,
        "template_digest": application_blueprint_digest(blueprint),
    }
