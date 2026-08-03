from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from .adapter_templates import (
    CONFIG_YAML,
    REPO_PYTHON,
    REPO_REEXPORT,
    SUPPORTED_ADAPTERS,
    render,
    render_container,
)
from .entity_scanner import EntityInfo, scan_entities, scan_installed_adapters
from .project_paths import ProjectPaths, detect_project_paths

console = Console()


# ── Entry point ───────────────────────────────────────────────────────────────

def add_adapter_cmd() -> None:
    """Wizard interactif pour scaffolder un nouvel adapter output."""
    project_dir = Path.cwd()

    _assert_arclith_project(project_dir)

    adapter = _prompt_adapter_type()
    entities = _prompt_entities(project_dir)
    params = _prompt_adapter_params(adapter, project_dir)
    activate = Confirm.ask(
        f"\n  [bold]Activer[/bold] [green]{adapter}[/green] maintenant ?",
        default=True,
    )

    _show_recap(project_dir, adapter, entities, params, activate)

    if not Confirm.ask("\n  [bold]Confirmer la génération ?[/bold]", default=True):
        console.print("[yellow]Annulé.[/yellow]")
        raise typer.Exit(0)

    _generate(project_dir, adapter, entities, params, activate)


# ── Validation ────────────────────────────────────────────────────────────────

def _assert_arclith_project(project_dir: Path) -> None:
    paths = detect_project_paths(project_dir)
    if not paths.domain_models.exists():
        console.print(
            "[red]✗[/red] Aucun dossier [bold]domain/models[/bold] ou [bold]src/<package>/domain/models[/bold] trouvé.\n"
            "    Exécutez [bold]arclith-cli add-adapter[/bold] depuis la racine d'un projet arclith."
        )
        raise typer.Exit(1)
    if not (project_dir / "config" / "adapters").exists():
        console.print(
            "[red]✗[/red] Aucun dossier [bold]config/adapters/[/bold] trouvé.\n"
            "    Le projet doit utiliser la structure [bold]config/[/bold] directory."
        )
        raise typer.Exit(1)


# ── Step 1 : adapter type ─────────────────────────────────────────────────────

def _prompt_adapter_type() -> str:
    console.print("\n[bold]① Type d'adapter[/bold]")
    for i, name in enumerate(SUPPORTED_ADAPTERS, 1):
        console.print(f"   [bold cyan]{i}[/bold cyan]  {name}")

    while True:
        raw = Prompt.ask("\n  Votre choix [dim](numéro ou nom)[/dim]").strip()
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(SUPPORTED_ADAPTERS):
                return SUPPORTED_ADAPTERS[idx]
        elif raw in SUPPORTED_ADAPTERS:
            return raw
        console.print(f"  [red]Choix invalide.[/red] Entrez 1-{len(SUPPORTED_ADAPTERS)} ou le nom.")


# ── Step 2 : entity selection ─────────────────────────────────────────────────

def _prompt_entities(project_dir: Path) -> list[EntityInfo]:
    entities = scan_entities(project_dir)
    if not entities:
        console.print("[red]✗[/red] Aucune entité trouvée dans [bold]src/<package>/domain/models/[/bold].")
        raise typer.Exit(1)

    console.print("\n[bold]② Entité(s) cible(s)[/bold]")
    for i, e in enumerate(entities, 1):
        console.print(f"   [bold cyan]{i}[/bold cyan]  {e.pascal} [dim]({e.snake})[/dim]")
    console.print(f"   [bold cyan]{len(entities) + 1}[/bold cyan]  [italic]toutes[/italic]")

    while True:
        raw = Prompt.ask("\n  Votre choix [dim](numéro(s) séparés par virgule, ou nom)[/dim]").strip()
        selected = _parse_entity_choice(raw, entities)
        if selected is not None:
            return selected
        console.print("  [red]Choix invalide.[/red]")


def _parse_entity_choice(raw: str, entities: list[EntityInfo]) -> list[EntityInfo] | None:
    all_idx = len(entities) + 1
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    result: list[EntityInfo] = []
    for part in parts:
        if part.isdigit():
            idx = int(part)
            if idx == all_idx:
                return list(entities)
            if 1 <= idx <= len(entities):
                e = entities[idx - 1]
                if e not in result:
                    result.append(e)
            else:
                return None
        else:
            matched = [e for e in entities if e.pascal == part or e.snake == part]
            if not matched:
                return None
            for e in matched:
                if e not in result:
                    result.append(e)
    return result or None


# ── Step 3 : adapter-specific params ─────────────────────────────────────────

def _prompt_adapter_params(adapter: str, project_dir: Path) -> dict:
    console.print(f"\n[bold]③ Paramètres [green]{adapter}[/green][/bold]")

    if adapter == "mongodb":
        project_name = project_dir.name
        db_name = Prompt.ask(
            "  db_name",
            default=project_name,
        ).strip()
        multitenant = Confirm.ask("  multitenant", default=False)
        return {"db_name": db_name, "multitenant": multitenant}

    if adapter == "duckdb":
        path = Prompt.ask("  path", default="data/").strip()
        return {"path": path}

    console.print("  [dim](aucun paramètre requis)[/dim]")
    return {}


# ── Step 4 : recap ────────────────────────────────────────────────────────────

def _show_recap(
    project_dir: Path,
    adapter: str,
    entities: list[EntityInfo],
    params: dict,
    activate: bool,
) -> None:
    installed = scan_installed_adapters(project_dir)
    paths = detect_project_paths(project_dir)
    files = _list_generated_files(project_dir, paths, adapter, entities, installed)

    table = Table(show_header=True, header_style="bold blue", box=None, padding=(0, 2))
    table.add_column("Fichier")
    table.add_column("Action", style="dim")

    for path, action in files:
        style = "yellow" if action == "remplacé ⚠" else "green"
        table.add_row(str(path.relative_to(project_dir)), f"[{style}]{action}[/{style}]")

    if activate:
        cfg_path = project_dir / "config" / "adapters" / "adapters.yaml"
        table.add_row(
            str(cfg_path.relative_to(project_dir)),
            "[cyan]mis à jour (repository)[/cyan]",
        )

    console.print()
    console.print(Panel(table, title=f"[bold]Récapitulatif — adapter [green]{adapter}[/green][/bold]"))


def _list_generated_files(
    project_dir: Path,
    paths: ProjectPaths,
    adapter: str,
    entities: list[EntityInfo],
    installed: list[str],
) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []

    if adapter != "memory" and CONFIG_YAML.get(adapter):
        cfg = project_dir / "config" / "adapters" / "output" / f"{adapter}.yaml"
        files.append((cfg, "remplacé ⚠" if cfg.exists() else "créé"))

    for entity in entities:
        base = paths.adapters_output / adapter
        repo_dir = base / "repositories"
        repo_file = repo_dir / f"{entity.snake}_repository.py"
        reexport = base / "repository.py"
        init = base / "__init__.py"
        container = paths.containers / f"{entity.snake}_container.py"

        files.append((init, "remplacé ⚠" if init.exists() else "créé"))
        files.append((repo_file, "remplacé ⚠" if repo_file.exists() else "créé"))
        files.append((reexport, "remplacé ⚠" if reexport.exists() else "créé"))
        files.append((container, "remplacé ⚠" if container.exists() else "créé"))

    return files


# ── Step 5 : generate ─────────────────────────────────────────────────────────

def _generate(
    project_dir: Path,
    adapter: str,
    entities: list[EntityInfo],
    params: dict,
    activate: bool,
) -> None:
    installed = scan_installed_adapters(project_dir)
    paths = detect_project_paths(project_dir)
    if adapter not in installed:
        installed = sorted(installed + [adapter])

    # Config YAML (skip memory — no config needed)
    if adapter != "memory":
        yaml_content = CONFIG_YAML.get(adapter, "")
        if yaml_content:
            cfg_path = project_dir / "config" / "adapters" / "output" / f"{adapter}.yaml"
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(render(yaml_content, params))
            console.print(f"[green]✓[/green] {cfg_path.relative_to(project_dir)}")

    for entity in entities:
        import_vars = _import_vars(paths)
        vars = {"pascal": entity.pascal, "snake": entity.snake, **params, **import_vars}
        base = paths.adapters_output / adapter
        repo_dir = base / "repositories"
        repo_dir.mkdir(parents=True, exist_ok=True)

        # __init__.py
        init_file = base / "__init__.py"
        if not init_file.exists():
            init_file.write_text("")
        # repositories/__init__.py
        repo_init_file = repo_dir / "__init__.py"
        if not repo_init_file.exists():
            repo_init_file.write_text("")
            console.print(f"[green]✓[/green] {repo_init_file.relative_to(project_dir)}")

        # Repository subclass
        repo_file = repo_dir / f"{entity.snake}_repository.py"
        repo_file.write_text(render(REPO_PYTHON[adapter], vars))
        console.print(f"[green]✓[/green] {repo_file.relative_to(project_dir)}")

        # Re-export
        reexport = base / "repository.py"
        reexport.write_text(render(REPO_REEXPORT[adapter], vars))
        console.print(f"[green]✓[/green] {reexport.relative_to(project_dir)}")

        # Container (full regeneration)
        container = paths.containers / f"{entity.snake}_container.py"
        existed = container.exists()
        container.parent.mkdir(parents=True, exist_ok=True)
        container.write_text(render_container(entity.pascal, entity.snake, installed, import_vars))
        action = "[yellow]remplacé ⚠[/yellow]" if existed else "[green]créé[/green]"
        console.print(f"{action} {container.relative_to(project_dir)}")

    # Activate: update config/adapters/adapters.yaml
    if activate:
        _update_active_adapter(project_dir, adapter)

    console.print(f"\n[bold green]✓ Adapter [cyan]{adapter}[/cyan] scaffoldé avec succès.[/bold green]")


def _import_vars(paths: ProjectPaths) -> dict[str, str]:
    return {
        "domain_import": paths.import_path("domain"),
        "application_import": paths.import_path("application"),
        "adapters_import": paths.import_path("adapters"),
        "infrastructure_import": paths.import_path("infrastructure"),
    }


def _update_active_adapter(project_dir: Path, adapter: str) -> None:
    import re
    cfg = project_dir / "config" / "adapters" / "adapters.yaml"
    if not cfg.exists():
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(f"repository: {adapter}\n")
    else:
        text = cfg.read_text()
        if re.search(r"(?m)^repository:", text):
            text = re.sub(r"(?m)^(repository:\s*).*$", rf"\g<1>{adapter}", text)
        else:
            text = text.rstrip("\n") + f"\nrepository: {adapter}\n"
        cfg.write_text(text)
    console.print(f"[cyan]↺[/cyan] config/adapters/adapters.yaml → repository: {adapter}")
