from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from arclith_cli.adapter_generator import GenerationRequest, _generate
from arclith_cli.adapter_parameters import (  # noqa: F401
    _resolve_adapter_params,
    _resolve_parameter,
)
from arclith_cli.adapter_rendering import _file_template_vars
from arclith_cli.adapter_selection import (
    _assert_arclith_project,
    _assert_capability_prerequisites,
    _resolve_adapter_type,
    _resolve_capability,
    _resolve_entities,
    _resolve_profile,
)
from arclith_cli.adapter_templates import render
from arclith_cli.capabilities import AdapterSpec, CapabilitySpec
from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.project_paths import ProjectPaths, detect_project_paths

console = Console()


@dataclass(frozen=True)
class AdapterCommandResult:
    """Resolved inputs that produced one successful adapter generation."""

    project_dir: Path
    capability: CapabilitySpec
    adapter: AdapterSpec
    entities: tuple[EntityInfo, ...]
    params: dict[str, Any]
    activate: bool
    profile: str | None


def add_adapter_cmd(
    *,
    project_dir: Path | None = None,
    capability_name: str = "repository",
    adapter: str | None = None,
    entity_names: list[str] | None = None,
    all_entities: bool = False,
    activate: bool = True,
    db_name: str | None = None,
    multitenant: bool | None = None,
    duckdb_path: str | None = None,
    adapter_params: dict[str, str] | None = None,
    profile: str | None = None,
    yes: bool = False,
) -> AdapterCommandResult:
    """Wizard interactif pour scaffolder un adapter du catalogue."""
    project_dir = project_dir or Path.cwd()

    _assert_arclith_project(project_dir)

    capability = _resolve_capability(capability_name)
    adapter_spec = _resolve_adapter_type(capability, adapter)
    _assert_capability_prerequisites(project_dir, adapter_spec)
    adapter = adapter_spec.name
    entities = _resolve_entities(
        project_dir, entity_names, all_entities, yes=yes, adapter=adapter_spec
    )
    profile_values = _resolve_profile(adapter_spec, profile)
    params = _resolve_adapter_params(
        adapter_spec,
        project_dir,
        db_name=db_name,
        multitenant=multitenant,
        duckdb_path=duckdb_path,
        extra_params={**profile_values, **(adapter_params or {})},
        prompt_missing=not yes,
    )
    if capability.activation_config_key is None:
        activate = False
    elif not yes:
        activate = Confirm.ask(
            f"\n  [bold]Activer[/bold] [green]{adapter}[/green] maintenant ?",
            default=activate,
        )

    _show_recap(project_dir, capability, adapter_spec, entities, params, activate)

    if not yes and not Confirm.ask(
        "\n  [bold]Confirmer la génération ?[/bold]", default=True
    ):
        console.print("[yellow]Annulé.[/yellow]")
        raise typer.Exit(0)

    explicit_params = {*profile_values, *(adapter_params or {})}
    _generate(
        GenerationRequest(
            project_dir=project_dir,
            capability=capability,
            adapter=adapter_spec,
            entities=entities,
            params=params,
            activate=activate,
            explicit_params=explicit_params,
        )
    )
    recorded_params = {
        parameter.name: params.get(parameter.name)
        for parameter in adapter_spec.parameters
    }
    return AdapterCommandResult(
        project_dir=project_dir,
        capability=capability,
        adapter=adapter_spec,
        entities=tuple(entities),
        params=recorded_params,
        activate=activate,
        profile=profile,
    )


# ── Validation ────────────────────────────────────────────────────────────────


def _show_recap(
    project_dir: Path,
    capability: CapabilitySpec,
    adapter: AdapterSpec,
    entities: list[EntityInfo],
    params: dict[str, Any],
    activate: bool,
) -> None:
    paths = detect_project_paths(project_dir)
    files = _list_generated_files(project_dir, paths, adapter, entities)

    table = Table(show_header=True, header_style="bold blue", box=None, padding=(0, 2))
    table.add_column("Fichier")
    table.add_column("Action", style="dim")

    for path, action in files:
        style = "yellow" if action == "remplacé ⚠" else "green"
        table.add_row(
            str(path.relative_to(project_dir)), f"[{style}]{action}[/{style}]"
        )

    if activate and capability.activation_config_key is not None:
        cfg_path = project_dir / "config" / "adapters" / "adapters.yaml"
        table.add_row(
            str(cfg_path.relative_to(project_dir)),
            f"[cyan]mis à jour ({_activation_config_label(capability)})[/cyan]",
        )

    console.print()
    console.print(
        Panel(
            table,
            title=f"[bold]Récapitulatif — adapter [green]{adapter.name}[/green][/bold]",
        )
    )


def _list_generated_files(
    project_dir: Path,
    paths: ProjectPaths,
    adapter: AdapterSpec,
    entities: list[EntityInfo],
) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []

    if adapter.has_config() and adapter.config_path:
        cfg = project_dir / adapter.config_path
        files.append((cfg, "remplacé ⚠" if cfg.exists() else "créé"))

    for merge_template in adapter.merge_config_templates:
        cfg = project_dir / render(merge_template.path, {})
        files.append((cfg, "mis à jour" if cfg.exists() else "créé"))

    if adapter.has_env() and adapter.env_path:
        env_file = project_dir / adapter.env_path
        files.append((env_file, "mis à jour" if env_file.exists() else "créé"))
        gitignore = project_dir / ".gitignore"
        files.append((gitignore, "mis à jour" if gitignore.exists() else "créé"))

    if adapter.has_secret_mappings() or adapter.has_secret_config():
        secrets_file = project_dir / "config" / "secrets.yaml"
        files.append((secrets_file, "mis à jour" if secrets_file.exists() else "créé"))

    if adapter.gitignore_entries:
        gitignore = project_dir / ".gitignore"
        files.append((gitignore, "mis à jour" if gitignore.exists() else "créé"))

    template_vars = _file_template_vars(project_dir, paths, adapter, params={})
    for file_template in adapter.file_templates:
        path = project_dir / render(file_template.path, template_vars)
        files.append((path, "remplacé ⚠" if path.exists() else "créé"))

    for entity in entities:
        base = paths.adapters_outbound / adapter.name
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


def _activation_config_label(capability: CapabilitySpec) -> str:
    if capability.name == "observability":
        return "observability.enabled"
    return capability.activation_config_key or ""


# ── Step 5 : generate ─────────────────────────────────────────────────────────
