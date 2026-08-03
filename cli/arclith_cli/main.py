from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.tree import Tree

from . import __version__
from .add_adapter import add_adapter_cmd
from .export_config import export_config_cmd
from .rename import EntityNames, apply_rename
from .scaffold import download_and_extract
from .updater import run_update

app = typer.Typer(
    name="arclith-cli",
    help="Scaffold [bold]arclith[/bold] hexagonal projects from the official template.",
    no_args_is_help=False,
    rich_markup_mode="rich",
)
console = Console()

_ENTITY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")
_PROJECT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")


@app.command()
def new(
    entity: Annotated[
        str | None,
        typer.Argument(
            help="Nom de l'entité au [bold]singulier[/bold] — tout format accepté : [dim]Recipe[/dim], [dim]recipe_step[/dim], [dim]meal-plan[/dim]",
        ),
    ] = None,
    project_name: Annotated[
        str | None,
        typer.Argument(help="Nom du répertoire du projet. Exemple : [dim]my-recipe-service[/dim]"),
    ] = None,
    directory: Annotated[
        Path,
        typer.Option("--dir", "-d", help="Répertoire parent où le projet sera créé"),
    ] = Path("."),
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Port REST (MCP = port+1)"),
    ] = 8000,
    repo_ref: Annotated[
        str,
        typer.Option("--ref", help="Branche ou tag Git du template _sample"),
    ] = "main",
    template_dir: Annotated[
        Path | None,
        typer.Option("--template-dir", help="Répertoire local du template _sample", hidden=True),
    ] = None,
) -> None:
    """Créer un nouveau projet [bold]arclith[/bold] scaffoldé depuis le template officiel [dim]_sample[/dim]."""
    entity = entity or _prompt_entity()
    project_name = project_name or _prompt_project()

    names = EntityNames.from_input(entity)
    target_dir = directory.resolve() / project_name

    if target_dir.exists():
        console.print(f"[red]✗[/red] Le répertoire existe déjà : [bold]{target_dir}[/bold]")
        raise typer.Exit(1)

    console.print(
        Panel.fit(
            f"[bold blue]arclith-cli[/bold blue] [dim]v{__version__}[/dim]\n\n"
            f"  Entité   [bold green]{names.pascal}[/bold green]  [dim]({names.snake} / {names.upper})[/dim]\n"
            f"  Projet   [bold]{project_name}[/bold]\n"
            f"  Cible    [dim]{target_dir}[/dim]\n"
            f"  Ports    REST [bold]{port}[/bold]  ·  MCP [bold]{port + 1}[/bold]",
            border_style="blue",
            title="[bold]Nouveau projet[/bold]",
        )
    )

    with console.status("[bold]Préparation du template…[/bold]"):
        try:
            download_and_extract(target_dir, ref=repo_ref, template_dir=template_dir)
        except Exception as exc:
            console.print(f"[red]✗ Téléchargement échoué :[/red] {exc}")
            raise typer.Exit(1) from exc

    console.print("[green]✓[/green] Template extrait")

    with console.status("[bold]Renommage de l'entité…[/bold]"):
        apply_rename(target_dir, names, project_name=project_name, port=port)

    console.print("[green]✓[/green] Renommage terminé")
    _print_summary(target_dir, project_name, port)


@app.command()
def update(
    ref: Annotated[
        str | None,
        typer.Option("--ref", help="Branche ou tag Git cible (défaut : main)"),
    ] = None,
) -> None:
    """Mettre à jour arclith-cli vers la dernière version depuis GitHub."""
    run_update(ref=ref)


@app.command()
def version() -> None:
    """Show the arclith-cli version."""
    console.print(f"arclith-cli [bold]{__version__}[/bold]")


@app.command(name="add-adapter")
def add_adapter(
    adapter: Annotated[
        str | None,
        typer.Option("--adapter", "-a", help="Adapter à générer: memory, mongodb ou duckdb"),
    ] = None,
    entity: Annotated[
        str | None,
        typer.Option("--entity", "-e", help="Entité cible. Liste séparée par virgule acceptée."),
    ] = None,
    all_entities: Annotated[
        bool,
        typer.Option("--all-entities", help="Générer l'adapter pour toutes les entités détectées"),
    ] = False,
    activate: Annotated[
        bool,
        typer.Option("--activate/--no-activate", help="Mettre à jour config/adapters/adapters.yaml"),
    ] = True,
    db_name: Annotated[
        str | None,
        typer.Option("--db-name", help="Nom de base MongoDB pour l'adapter mongodb"),
    ] = None,
    multitenant: Annotated[
        bool | None,
        typer.Option("--multitenant/--single-tenant", help="Mode multitenant MongoDB"),
    ] = None,
    path: Annotated[
        str | None,
        typer.Option("--path", help="Chemin de stockage pour l'adapter duckdb"),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Utiliser les valeurs fournies ou par défaut sans confirmation"),
    ] = False,
) -> None:
    """Wizard ou mode direct pour scaffolder un nouvel [bold]adapter output[/bold] dans le projet courant."""
    add_adapter_cmd(
        adapter=adapter,
        entity_names=_split_entity_option(entity),
        all_entities=all_entities,
        activate=activate,
        db_name=db_name,
        multitenant=multitenant,
        duckdb_path=path,
        yes=yes,
    )


@app.command(name="export-config")
def export_config(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Chemin du fichier YAML généré"),
    ] = Path("config.yaml"),
) -> None:
    """Générer un [bold]config.yaml[/bold] unifié depuis [bold]config/[/bold] pour déploiement K8s."""
    export_config_cmd(output=output)


# ── Prompts interactifs ───────────────────────────────────────────────────────

def _prompt_entity() -> str:
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


def _prompt_project() -> str:
    console.print("\n[bold]Projet[/bold] [dim](ex : my-recipe-service, meal-planner)[/dim]")
    while True:
        value = Prompt.ask("  [bold green]Nom du projet[/bold green]").strip()
        if not value:
            console.print("  [red]Le nom ne peut pas être vide.[/red]")
        elif not _PROJECT_RE.match(value):
            console.print(
                "  [red]Caractères invalides.[/red] "
                "[dim]Lettres, chiffres, _ et - uniquement. Doit commencer par une lettre.[/dim]"
            )
        else:
            return value


# ── Helpers ───────────────────────────────────────────────────────────────────

def _split_entity_option(value: str | None) -> list[str] | None:
    if value is None:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def _print_summary(target_dir: Path, project_name: str, port: int) -> None:
    tree = Tree(f"[bold green]{project_name}/[/bold green]")
    _build_tree(tree, target_dir, depth=0, max_depth=3)
    console.print()
    console.print(tree)
    console.print(
        Panel(
            f"[bold cyan]cd[/bold cyan] {target_dir}\n"
            f"[bold cyan]uv sync[/bold cyan]\n\n"
            f"[bold cyan]uv run python main.py[/bold cyan]"
            f"  [dim]# MODE=api → REST :{port}[/dim]\n"
            f"[bold cyan]MODE=mcp_http uv run python main.py[/bold cyan]"
            f"  [dim]# MCP :{port + 1}[/dim]",
            title="[bold blue]Next steps[/bold blue]",
            border_style="green",
        )
    )


def _build_tree(node: Tree, path: Path, depth: int, max_depth: int) -> None:
    if depth >= max_depth:
        return
    try:
        children = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
    except PermissionError:
        return
    for child in children:
        if child.name.startswith("."):
            continue
        label = f"[blue]{child.name}/[/blue]" if child.is_dir() else child.name
        branch = node.add(label)
        if child.is_dir():
            _build_tree(branch, child, depth + 1, max_depth)
