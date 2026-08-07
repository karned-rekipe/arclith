from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console

from .project_paths import ProjectPaths, detect_project_paths
from .rename import EntityNames

console = Console()

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")

_ENTITY_TEMPLATE = """from arclith.domain.models.entity import Entity


class {class_name}(Entity):
    pass
"""

_INBOUND_PORT_TEMPLATE = """from abc import ABC, abstractmethod


class {class_name}Port(ABC):
    @abstractmethod
    async def execute(self) -> None:
        raise NotImplementedError
"""

_USE_CASE_TEMPLATE = """from {inbound_port_module} import {class_name}Port


class {class_name}UseCase({class_name}Port):
    async def execute(self) -> None:
        raise NotImplementedError("Implement {class_name}UseCase.execute")
"""

_PLANNER_TEMPLATE = """class {class_name}Planner:
    async def plan(self, prompt: str) -> None:
        raise NotImplementedError("Implement {class_name}Planner.plan")
"""


@dataclass(frozen=True)
class UseCaseNames:
    pascal: str
    snake: str

    @classmethod
    def from_input(cls, raw: str) -> UseCaseNames:
        names = EntityNames.from_input(raw)
        pascal = _strip_pascal_suffix(names.pascal)
        snake = _strip_snake_suffix(names.snake)
        if not pascal or not snake:
            console.print(f"[red]✗[/red] Nom de cas d'usage invalide : [bold]{raw}[/bold].")
            raise typer.Exit(1)
        return cls(pascal=pascal, snake=snake)


@dataclass(frozen=True)
class PlannerNames:
    pascal: str
    snake: str

    @classmethod
    def from_input(cls, raw: str) -> PlannerNames:
        names = EntityNames.from_input(raw)
        pascal = _strip_pascal_planner_suffix(names.pascal)
        snake = _strip_snake_planner_suffix(names.snake)
        if not pascal or not snake:
            console.print(f"[red]✗[/red] Nom de planner invalide : [bold]{raw}[/bold].")
            raise typer.Exit(1)
        return cls(pascal=pascal, snake=snake)


def add_entity_cmd(*, project_dir: Path | None = None, entity_name: str) -> Path:
    project_dir = project_dir or Path.cwd()
    entity_name = entity_name.strip()
    _assert_project_root(project_dir, command="add-entity")
    _assert_valid_name(entity_name, label="entité")

    paths = detect_project_paths(project_dir)
    names = EntityNames.from_input(entity_name)
    entity_file = paths.domain_models / f"{names.snake}.py"
    _assert_missing(entity_file, project_dir)

    _ensure_package_dirs(paths, "domain", "models")
    entity_file.write_text(_ENTITY_TEMPLATE.format(class_name=names.pascal), encoding="utf-8")
    console.print(
        f"[green]✓[/green] Entité {names.pascal} créée : "
        f"[bold]{entity_file.relative_to(project_dir)}[/bold]"
    )
    return entity_file


def add_usecase_cmd(*, project_dir: Path | None = None, usecase_name: str) -> Path:
    project_dir = project_dir or Path.cwd()
    usecase_name = usecase_name.strip()
    _assert_project_root(project_dir, command="add-usecase")
    _assert_valid_name(usecase_name, label="cas d'usage")

    paths = detect_project_paths(project_dir)
    names = UseCaseNames.from_input(usecase_name)
    usecase_file = paths.application_use_cases / f"{names.snake}.py"
    inbound_port_file = paths.inbound_ports / f"{names.snake}.py"
    _assert_missing(usecase_file, project_dir)
    _assert_missing(inbound_port_file, project_dir)

    _ensure_package_dirs(paths, "domain", "ports", "inbound")
    _ensure_package_dirs(paths, "application", "use_cases")
    inbound_port_file.write_text(_INBOUND_PORT_TEMPLATE.format(class_name=names.pascal), encoding="utf-8")
    usecase_file.write_text(
        _USE_CASE_TEMPLATE.format(
            class_name=names.pascal,
            inbound_port_module=paths.import_path("domain", "ports", "inbound", names.snake),
        ),
        encoding="utf-8",
    )
    console.print(
        f"[green]✓[/green] Port inbound {names.pascal}Port créé : "
        f"[bold]{inbound_port_file.relative_to(project_dir)}[/bold]"
    )
    console.print(
        f"[green]✓[/green] Cas d'usage {names.pascal}UseCase créé : "
        f"[bold]{usecase_file.relative_to(project_dir)}[/bold]"
    )
    return usecase_file


def add_planner_cmd(*, project_dir: Path | None = None, planner_name: str) -> Path:
    project_dir = project_dir or Path.cwd()
    planner_name = planner_name.strip()
    _assert_project_root(project_dir, command="add-planner")
    _assert_valid_name(planner_name, label="planner")

    paths = detect_project_paths(project_dir)
    names = PlannerNames.from_input(planner_name)
    planner_file = paths.application_planners / f"{names.snake}.py"
    _assert_missing(planner_file, project_dir)

    _ensure_package_dirs(paths, "application", "planners")
    planner_file.write_text(_PLANNER_TEMPLATE.format(class_name=names.pascal), encoding="utf-8")
    console.print(
        f"[green]✓[/green] Planner {names.pascal}Planner créé : "
        f"[bold]{planner_file.relative_to(project_dir)}[/bold]"
    )
    return planner_file


def _assert_project_root(project_dir: Path, *, command: str) -> None:
    if not project_dir.exists() or not project_dir.is_dir():
        console.print(f"[red]✗[/red] Répertoire introuvable : [bold]{project_dir}[/bold].")
        raise typer.Exit(1)

    has_project_marker = (
        (project_dir / "pyproject.toml").exists()
        or (project_dir / "src").is_dir()
        or (project_dir / "config").is_dir()
    )
    if has_project_marker:
        return

    console.print(
        f"[red]✗[/red] Aucun projet arclith détecté.\n"
        f"    Exécutez [bold]arclith-cli {command}[/bold] depuis la racine du projet."
    )
    raise typer.Exit(1)


def _assert_valid_name(raw: str, *, label: str) -> None:
    if _NAME_RE.match(raw.strip()):
        return

    console.print(
        f"[red]✗[/red] Nom de {label} invalide : [bold]{raw}[/bold]. "
        "Lettres, chiffres, _ et - uniquement. Doit commencer par une lettre."
    )
    raise typer.Exit(1)


def _assert_missing(path: Path, project_dir: Path) -> None:
    if not path.exists():
        return

    console.print(f"[red]✗[/red] Le fichier existe déjà : [bold]{path.relative_to(project_dir)}[/bold].")
    raise typer.Exit(1)


def _ensure_package_dirs(paths: ProjectPaths, *relative_parts: str) -> None:
    target_dir = paths.package_root.joinpath(*relative_parts)
    target_dir.mkdir(parents=True, exist_ok=True)

    stop_at = paths.package_root.parent if paths.package_name is not None else paths.package_root
    init_dirs = [target_dir]
    for parent in target_dir.parents:
        if parent == stop_at:
            break
        init_dirs.append(parent)

    for directory in init_dirs:
        init_file = directory / "__init__.py"
        if not init_file.exists():
            init_file.write_text("", encoding="utf-8")


def _strip_pascal_suffix(value: str) -> str:
    suffixes = ("UseCase", "Usecase")
    while True:
        stripped = value
        for suffix in suffixes:
            if stripped.endswith(suffix):
                stripped = stripped[: -len(suffix)]
                break
        if stripped == value:
            return value
        value = stripped


def _strip_snake_suffix(value: str) -> str:
    suffixes = ("_use_case", "_usecase")
    while True:
        stripped = value
        for suffix in suffixes:
            if stripped.endswith(suffix):
                stripped = stripped[: -len(suffix)]
                break
        if stripped == value:
            return value
        value = stripped


def _strip_pascal_planner_suffix(value: str) -> str:
    suffixes = ("Planner",)
    while True:
        stripped = value
        for suffix in suffixes:
            if stripped.endswith(suffix):
                stripped = stripped[: -len(suffix)]
                break
        if stripped == value:
            return value
        value = stripped


def _strip_snake_planner_suffix(value: str) -> str:
    suffixes = ("_planner",)
    while True:
        stripped = value
        for suffix in suffixes:
            if stripped.endswith(suffix):
                stripped = stripped[: -len(suffix)]
                break
        if stripped == value:
            return value
        value = stripped
