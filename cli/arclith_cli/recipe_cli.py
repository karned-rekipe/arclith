from __future__ import annotations

from pathlib import Path
from typing import Annotated, Never

import typer
from rich.console import Console
from rich.table import Table

from arclith_cli.recipe import (
    RECIPE_FILENAME,
    RecipeError,
    load_recipe,
    plan_replay_steps,
    replay_recipe,
    required_replay_env,
    select_recipe_steps,
    step_summary,
)

console = Console()


def history_command(
    recipe_path: Annotated[
        Path,
        typer.Option(
            "--recipe",
            help="Recette à afficher (défaut: arclith.recipe.yaml).",
        ),
    ] = Path(RECIPE_FILENAME),
) -> None:
    """Afficher la timeline des mutations enregistrées par [bold]arclith-cli[/bold]."""
    try:
        recipe = load_recipe(recipe_path)
    except RecipeError as exc:
        _recipe_error(exc)

    table = Table(show_header=True, header_style="bold blue", box=None, padding=(0, 2))
    table.add_column("ID", style="cyan")
    table.add_column("Date")
    table.add_column("Commande", style="green")
    table.add_column("Résumé")
    for step in recipe.steps:
        table.add_row(step.id, step.at, step.command, step_summary(step))
    console.print(table)


def replay_command(
    recipe_path: Annotated[
        Path,
        typer.Argument(help="Chemin du fichier arclith.recipe.yaml à rejouer."),
    ],
    directory: Annotated[
        Path,
        typer.Option("--dir", "-d", help="Répertoire projet cible."),
    ],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Afficher le plan sans modifier le disque."),
    ] = False,
    from_step: Annotated[
        str | None,
        typer.Option("--from-step", help="Premier id de step à rejouer (inclus)."),
    ] = None,
    to_step: Annotated[
        str | None,
        typer.Option("--to-step", help="Dernier id de step à rejouer (inclus)."),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Échouer si une commande de la recette n'est pas supportée.",
        ),
    ] = False,
) -> None:
    """Rejouer une recette via les fonctions Python existantes de la CLI."""
    try:
        recipe = load_recipe(recipe_path)
        steps = select_recipe_steps(
            recipe,
            from_step=from_step,
            to_step=to_step,
        )
        planned_steps = plan_replay_steps(steps, strict=strict)
    except RecipeError as exc:
        _recipe_error(exc)

    table = Table(show_header=True, header_style="bold blue", box=None, padding=(0, 2))
    table.add_column("ID", style="cyan")
    table.add_column("Commande", style="green")
    table.add_column("Résumé")
    table.add_column("Action")
    planned_ids = {step.id for step in planned_steps}
    for step in steps:
        action = "rejouer" if step.id in planned_ids else "ignorer (non supportée)"
        table.add_row(step.id, step.command, step_summary(step), action)
    console.print(table)

    required_env = required_replay_env(planned_steps)
    if required_env:
        console.print(
            "[yellow]Secrets requis via l'environnement :[/yellow] "
            + ", ".join(required_env)
        )
    if dry_run:
        skipped_count = len(steps) - len(planned_steps)
        console.print(
            f"[bold cyan]Dry-run :[/bold cyan] {len(planned_steps)} étape(s) "
            f"à exécuter, {skipped_count} ignorée(s), aucune écriture dans "
            f"{directory}."
        )
        return
    if not planned_steps:
        console.print("[yellow]Aucune étape supportée à rejouer.[/yellow]")
        return

    try:
        executed = replay_recipe(
            recipe,
            steps,
            target_dir=directory,
            strict=strict,
        )
    except RecipeError as exc:
        _recipe_error(exc)
    console.print(
        f"[bold green]✓ Replay terminé : {len(executed)} étape(s) exécutée(s) "
        f"dans {directory.resolve()}.[/bold green]"
    )


def _recipe_error(exc: Exception) -> Never:
    console.print(f"[red]✗ Recette CLI invalide :[/red] {exc}")
    raise typer.Exit(1)
