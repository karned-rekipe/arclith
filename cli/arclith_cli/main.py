from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from . import __version__
from .add_adapter import add_adapter_cmd
from .adapter_blueprints import blueprint_digest, get_adapter_blueprint
from .application_blueprint_cli import (
    add_blueprint_command,
    add_entity_command,
    application_profile_recipe_metadata,
    blueprints_command,
    prompt_entity,
    resolve_entity_profile,
)
from .binding_cli import expose_usecase_command
from .capabilities import CAPABILITY_CATALOG, capability_catalog_as_dict
from .command_recording import record_success as _record_success
from .core_scaffold import add_intent_interpreter_cmd, add_usecase_cmd
from .export_config import export_config_cmd
from .feature_projection_cli import expose_feature_command
from .guide import guide_command, should_launch_guide
from .init_project import init_project_cmd
from .new_project import new_project_cmd as _new_project_cmd
from .project_status_cli import doctor_command, status_command
from .project_runtime_cli import run_command
from .recipe import (
    adapter_secret_metadata,
    snapshot_project_files,
)
from .recipe_cli import history_command, replay_command
from .scaffold_interactive import resolve_usecase_entity_choice
from .tui import run_tui, tui_command
from .updater import run_update

app = typer.Typer(
    name="arclith-cli",
    help="Build [bold]arclith[/bold] hexagonal projects through explicit capabilities.",
    invoke_without_command=True,
    no_args_is_help=False,
    rich_markup_mode="rich",
)
console = Console()
app.command(name="history")(history_command)
app.command(name="replay")(replay_command)
app.command(name="expose-usecase")(expose_usecase_command)
app.command(name="expose-feature")(expose_feature_command)
app.command(name="add-entity")(add_entity_command)
app.command(name="blueprints")(blueprints_command)
app.command(name="add-blueprint")(add_blueprint_command)
app.command(name="guide")(guide_command)
app.command(name="status")(status_command)
app.command(name="doctor")(doctor_command)
app.command(name="run")(run_command)
app.command(name="tui")(tui_command)

_ENTITY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")
_PROJECT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")


@app.callback()
def main(ctx: typer.Context) -> None:
    """Lancer le cockpit dans un terminal, sinon afficher l'aide stable."""
    if ctx.invoked_subcommand is None:
        if should_launch_guide():
            run_tui()
        else:
            typer.echo(ctx.get_help())


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
    no_record: Annotated[
        bool,
        typer.Option(
            "--no-record",
            help="Ne pas écrire la recette CLI (usage interne).",
            hidden=True,
        ),
    ] = False,
) -> None:
    """Initialiser un projet arclith minimal sans entité métier."""
    resolved_name = project_name or _prompt_project()
    target_dir = init_project_cmd(project_name=resolved_name, directory=directory)
    if not no_record:
        _record_success(
            target_dir,
            command="init",
            args={"project_name": resolved_name, "directory": "."},
            before={},
        )


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
        typer.Argument(
            help="Nom du répertoire du projet. Exemple : [dim]my-recipe-service[/dim]"
        ),
    ] = None,
    directory: Annotated[
        Path,
        typer.Option("--dir", "-d", help="Répertoire parent où le projet sera créé"),
    ] = Path("."),
    port: Annotated[
        int,
        typer.Option(
            "--port",
            "-p",
            help="Port REST suggéré pour un futur add-adapter api/fastapi",
        ),
    ] = 8000,
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            help="Profil applicatif initial : minimal ou un blueprint tel que crud.",
        ),
    ] = None,
    repo_ref: Annotated[
        str,
        typer.Option(
            "--ref",
            help="Option historique conservée pour le replay des anciennes recettes",
            hidden=True,
        ),
    ] = "main",
    template_dir: Annotated[
        Path | None,
        typer.Option(
            "--template-dir", help="Répertoire local du template _sample", hidden=True
        ),
    ] = None,
    no_record: Annotated[
        bool,
        typer.Option(
            "--no-record",
            help="Ne pas écrire la recette CLI (usage interne).",
            hidden=True,
        ),
    ] = False,
) -> None:
    """Raccourci canonique pour init puis add-entity, sans adapter implicite."""
    interactive = entity is None
    entity = entity or prompt_entity()
    try:
        resolved_profile = resolve_entity_profile(profile, interactive=interactive)
    except ValueError as exc:
        console.print(f"[red]✗ Profil invalide :[/red] {exc}")
        raise typer.Exit(1) from exc
    project_name = project_name or _prompt_project()
    target_dir = _new_project_cmd(
        entity=entity,
        project_name=project_name,
        directory=directory,
        port=port,
        repo_ref=repo_ref,
        template_dir=template_dir,
        profile=resolved_profile,
    )
    if not no_record:
        _record_success(
            target_dir,
            command="new",
            args={
                "entity": entity,
                "project_name": project_name,
                "directory": ".",
                "port": port,
                "repo_ref": repo_ref,
                "profile": resolved_profile,
                **application_profile_recipe_metadata(resolved_profile),
            },
            before={},
        )


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
        str | None,
        typer.Option(
            "--capability",
            help=(
                "Capacité cible: " + ", ".join(item.name for item in CAPABILITY_CATALOG)
            ),
        ),
    ] = None,
    adapter: Annotated[
        str | None,
        typer.Option("--adapter", "-a", help="Adapter à générer depuis le catalogue"),
    ] = None,
    entity: Annotated[
        str | None,
        typer.Option(
            "--entity",
            "-e",
            help="Option historique réservée aux anciens blueprints entity-scoped",
            hidden=True,
        ),
    ] = None,
    all_entities: Annotated[
        bool,
        typer.Option(
            "--all-entities",
            help="Option historique réservée aux anciens blueprints entity-scoped",
            hidden=True,
        ),
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
        typer.Option(
            "--param",
            help="Paramètre adapter key=value, répétable pour les adapters du catalogue",
        ),
    ] = None,
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            help="Profil explicite de l'adapter, par exemple development ou production",
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Utiliser les valeurs fournies ou par défaut sans confirmation",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Afficher le scaffold sans modifier les fichiers ou la recette.",
        ),
    ] = False,
    no_record: Annotated[
        bool,
        typer.Option(
            "--no-record",
            help="Ne pas écrire la recette CLI (usage interne).",
            hidden=True,
        ),
    ] = False,
) -> None:
    """Wizard ou mode direct pour scaffolder un nouvel [bold]adapter[/bold] dans le projet courant."""
    project_dir = Path.cwd()
    before = (
        snapshot_project_files(project_dir) if not no_record and not dry_run else {}
    )
    result = add_adapter_cmd(
        project_dir=project_dir,
        capability_name=capability,
        adapter=adapter,
        entity_names=_split_entity_option(entity),
        all_entities=all_entities,
        activate=activate,
        db_name=db_name,
        multitenant=multitenant,
        duckdb_path=path,
        adapter_params=_parse_param_options(param),
        profile=profile,
        yes=yes,
        dry_run=dry_run,
    )
    if not no_record and not dry_run:
        blueprint = get_adapter_blueprint(result.adapter)
        secret_fields, secret_references = adapter_secret_metadata(result.adapter)
        _record_success(
            project_dir,
            command="add-adapter",
            args={
                "capability": result.capability.name,
                "adapter": result.adapter.name,
                "entities": [entity.pascal for entity in result.entities],
                "activate": result.activate,
                "profile": result.profile,
                "params": result.params,
                "blueprint_version": blueprint.version,
                "template_digest": blueprint_digest(blueprint),
            },
            before=before,
            secret_fields=secret_fields,
            secret_references=secret_references,
        )


@app.command(name="add-usecase")
def add_usecase(
    usecase: Annotated[
        str | None,
        typer.Argument(
            help="Nom du cas d'usage. Exemple : PlanShoppingList, find_by_name, import-catalog",
        ),
    ] = None,
    entity: Annotated[
        str | None,
        typer.Option(
            "--entity",
            help="Lier le cas d'usage à une entité existante.",
        ),
    ] = None,
    new_entity: Annotated[
        str | None,
        typer.Option(
            "--new-entity",
            help="Créer l'entité si nécessaire, puis lier le cas d'usage.",
        ),
    ] = None,
    no_entity: Annotated[
        bool,
        typer.Option(
            "--no-entity",
            help="Générer un cas d'usage transverse sans repository.",
        ),
    ] = False,
    no_record: Annotated[
        bool,
        typer.Option("--no-record", hidden=True),
    ] = False,
) -> None:
    """Créer un port inbound et un cas d'usage guidés, liés ou transverses."""
    resolved_name = usecase or _prompt_usecase()
    project_dir = Path.cwd()
    entity_choice = resolve_usecase_entity_choice(
        project_dir=project_dir,
        entity_name=entity,
        new_entity_name=new_entity,
        no_entity=no_entity,
    )
    before = snapshot_project_files(project_dir) if not no_record else {}
    add_usecase_cmd(
        project_dir=project_dir,
        usecase_name=resolved_name,
        entity_name=entity_choice.entity_name,
        new_entity_name=entity_choice.new_entity_name,
    )
    if not no_record:
        _record_success(
            project_dir,
            command="add-usecase",
            args={
                "usecase": resolved_name,
                "entity": entity_choice.entity_name,
                "new_entity": entity_choice.new_entity_name,
                "no_entity": entity_choice.no_entity,
            },
            before=before,
        )


@app.command(name="add-intent-interpreter")
def add_intent_interpreter(
    intent: Annotated[
        str | None,
        typer.Argument(
            help="Nom de l'interpréteur d'intention. Exemple : IngredientIntent, todo-intent, command-router",
        ),
    ] = None,
    no_record: Annotated[
        bool,
        typer.Option("--no-record", hidden=True),
    ] = False,
) -> None:
    """Créer uniquement le fichier minimal d'un interpréteur d'intention."""
    resolved_name = intent or _prompt_intent_interpreter()
    project_dir = Path.cwd()
    before = snapshot_project_files(project_dir) if not no_record else {}
    add_intent_interpreter_cmd(project_dir=project_dir, intent_name=resolved_name)
    if not no_record:
        _record_success(
            project_dir,
            command="add-intent-interpreter",
            args={"intent": resolved_name},
            before=before,
        )


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


def _prompt_project() -> str:
    console.print(
        "\n[bold]Projet[/bold] [dim](ex : my-recipe-service, meal-planner)[/dim]"
    )
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
    console.print(
        "\n[bold]Cas d'usage[/bold] [dim](ex : PlanShoppingList, find_by_name)[/dim]"
    )
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
    console.print(
        "\n[bold]Interpréteur d'intention[/bold] [dim](ex : IngredientIntent, todo_intent)[/dim]"
    )
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
            console.print(
                f"[red]✗[/red] Paramètre invalide: [bold]{raw}[/bold]. Format attendu: key=value."
            )
            raise typer.Exit(1)
        result[key] = value.strip()
    return result
