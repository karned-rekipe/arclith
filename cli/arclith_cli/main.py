from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.tree import Tree

from . import __version__
from .add_adapter import add_adapter_cmd
from .capabilities import CAPABILITY_CATALOG, capability_catalog_as_dict
from .core_scaffold import add_entity_cmd, add_intent_interpreter_cmd, add_usecase_cmd
from .export_config import export_config_cmd
from .init_project import init_project_cmd
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
def init(
    project_name: Annotated[
        str | None,
        typer.Argument(help="Nom du répertoire du projet. Exemple : todo-list-service"),
    ] = None,
    directory: Annotated[
        Path,
        typer.Option("--dir", "-d", help="Répertoire parent où le projet sera créé"),
    ] = Path("."),
) -> None:
    """Initialiser un projet arclith minimal sans entité métier."""
    init_project_cmd(project_name=project_name or _prompt_project(), directory=directory)


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
    capability: Annotated[
        str,
        typer.Option("--capability", help="Capacité cible: repository, api, mcp, llm, agent ou observability"),
    ] = "repository",
    adapter: Annotated[
        str | None,
        typer.Option("--adapter", "-a", help="Adapter à générer depuis le catalogue"),
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
        typer.Option(
            "--activate/--no-activate",
            help="Mettre à jour config/adapters/adapters.yaml quand la capacité expose une clé d'activation",
        ),
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
    param: Annotated[
        list[str] | None,
        typer.Option("--param", help="Paramètre adapter key=value, répétable pour les adapters du catalogue"),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Utiliser les valeurs fournies ou par défaut sans confirmation"),
    ] = False,
) -> None:
    """Wizard ou mode direct pour scaffolder un nouvel [bold]adapter[/bold] dans le projet courant."""
    add_adapter_cmd(
        capability_name=capability,
        adapter=adapter,
        entity_names=_split_entity_option(entity),
        all_entities=all_entities,
        activate=activate,
        db_name=db_name,
        multitenant=multitenant,
        duckdb_path=path,
        adapter_params=_parse_param_options(param),
        yes=yes,
    )


@app.command(name="add-entity")
def add_entity(
    entity: Annotated[
        str | None,
        typer.Argument(
            help="Nom de l'entité métier au singulier. Exemple : Recipe, recipe_step, meal-plan",
        ),
    ] = None,
) -> None:
    """Créer uniquement le fichier minimal d'une entité métier dans domain/models."""
    add_entity_cmd(entity_name=entity or _prompt_entity())


@app.command(name="add-usecase")
def add_usecase(
    usecase: Annotated[
        str | None,
        typer.Argument(
            help="Nom du cas d'usage. Exemple : PlanShoppingList, find_by_name, import-catalog",
        ),
    ] = None,
) -> None:
    """Créer uniquement le fichier minimal d'un cas d'usage dans application/use_cases."""
    add_usecase_cmd(usecase_name=usecase or _prompt_usecase())


@app.command(name="add-intent-interpreter")
def add_intent_interpreter(
    intent: Annotated[
        str | None,
        typer.Argument(
            help="Nom de l'interpréteur d'intention. Exemple : IngredientIntent, todo-intent, command-router",
        ),
    ] = None,
) -> None:
    """Créer uniquement le fichier minimal d'un interpréteur d'intention."""
    add_intent_interpreter_cmd(intent_name=intent or _prompt_intent_interpreter())


@app.command(name="capabilities")
def capabilities(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Afficher le catalogue au format JSON"),
    ] = False,
) -> None:
    """Lister les capacités standardisées supportées par [bold]arclith-cli[/bold]."""
    if as_json:
        typer.echo(json.dumps(capability_catalog_as_dict(), indent=2))
        return

    table = Table(show_header=True, header_style="bold blue", box=None, padding=(0, 2))
    table.add_column("Capacité")
    table.add_column("Layer")
    table.add_column("Adapter")
    table.add_column("Config")
    table.add_column("Description")

    for capability_spec in CAPABILITY_CATALOG:
        for adapter_spec in capability_spec.adapters:
            table.add_row(
                capability_spec.name,
                adapter_spec.layer,
                adapter_spec.name,
                adapter_spec.config_path or "-",
                adapter_spec.description,
            )

    console.print(table)


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


def _prompt_usecase() -> str:
    console.print("\n[bold]Cas d'usage[/bold] [dim](ex : PlanShoppingList, find_by_name)[/dim]")
    while True:
        value = Prompt.ask("  [bold green]Nom du cas d'usage[/bold green]").strip()
        if not value:
            console.print("  [red]Le nom ne peut pas être vide.[/red]")
        elif not _ENTITY_RE.match(value):
            console.print(
                "  [red]Caractères invalides.[/red] "
                "[dim]Lettres, chiffres, _ et - uniquement. Doit commencer par une lettre.[/dim]"
            )
        else:
            return value


def _prompt_intent_interpreter() -> str:
    console.print("\n[bold]Interpréteur d'intention[/bold] [dim](ex : IngredientIntent, todo_intent)[/dim]")
    while True:
        value = Prompt.ask("  [bold green]Nom de l'interpréteur[/bold green]").strip()
        if not value:
            console.print("  [red]Le nom ne peut pas être vide.[/red]")
        elif not _ENTITY_RE.match(value):
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


def _parse_param_options(values: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in values or []:
        key, separator, value = raw.partition("=")
        key = key.strip()
        if separator != "=" or not key:
            console.print(f"[red]✗[/red] Paramètre invalide: [bold]{raw}[/bold]. Format attendu: key=value.")
            raise typer.Exit(1)
        result[key] = value.strip()
    return result


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
