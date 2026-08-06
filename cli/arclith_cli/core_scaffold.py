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

_USE_CASE_TEMPLATE = """class {class_name}UseCase:
    async def execute(self) -> None:
        raise NotImplementedError("Implement {class_name}UseCase.execute")
"""


@dataclass(frozen=True)
class UseCaseNames:
    pascal: str
    snake: str

    @classmethod
    def from_input(cls, raw: str) -> UseCaseNames:
        names = EntityNames.from_input(raw)
        pascal = _strip_pascal_suffix(names.pascal, "UseCase")
        snake = _strip_snake_suffix(names.snake)
        if not pascal or not snake:
            console.print(f"[red]x[/red] Nom de use case invalide: [bold]{raw}[/bold].")
            raise typer.Exit(1)
        return cls(pascal=pascal, snake=snake)


def add_entity_cmd(*, project_dir: Path | None = None, entity_name: str) -> Path:
    project_dir = project_dir or Path.cwd()
    entity_name = entity_name.strip()
    _assert_project_root(project_dir, command="add-entity")
    _assert_valid_name(entity_name, label="entite")

    paths = detect_project_paths(project_dir)
    names = EntityNames.from_input(entity_name)
    entity_file = paths.domain_models / f"{names.snake}.py"
    _assert_missing(entity_file, project_dir)

    _ensure_package_dirs(paths, "domain", "models")
    entity_file.write_text(_ENTITY_TEMPLATE.format(class_name=names.pascal), encoding="utf-8")
    console.print(
        f"[green]OK[/green] Entite {names.pascal} creee: "
        f"[bold]{entity_file.relative_to(project_dir)}[/bold]"
    )
    return entity_file


def add_usecase_cmd(*, project_dir: Path | None = None, usecase_name: str) -> Path:
    project_dir = project_dir or Path.cwd()
    usecase_name = usecase_name.strip()
    _assert_project_root(project_dir, command="add-usecase")
    _assert_valid_name(usecase_name, label="use case")

    paths = detect_project_paths(project_dir)
    names = UseCaseNames.from_input(usecase_name)
    usecase_file = paths.application_use_cases / f"{names.snake}.py"
    _assert_missing(usecase_file, project_dir)

    _ensure_package_dirs(paths, "application", "use_cases")
    usecase_file.write_text(_USE_CASE_TEMPLATE.format(class_name=names.pascal), encoding="utf-8")
    console.print(
        f"[green]OK[/green] Use case {names.pascal}UseCase cree: "
        f"[bold]{usecase_file.relative_to(project_dir)}[/bold]"
    )
    return usecase_file


def _assert_project_root(project_dir: Path, *, command: str) -> None:
    if not project_dir.exists() or not project_dir.is_dir():
        console.print(f"[red]x[/red] Repertoire introuvable: [bold]{project_dir}[/bold].")
        raise typer.Exit(1)

    has_project_marker = (
        (project_dir / "pyproject.toml").exists()
        or (project_dir / "src").is_dir()
        or (project_dir / "config").is_dir()
    )
    if has_project_marker:
        return

    console.print(
        f"[red]x[/red] Aucun projet arclith detecte.\n"
        f"    Executez [bold]arclith-cli {command}[/bold] depuis la racine du projet."
    )
    raise typer.Exit(1)


def _assert_valid_name(raw: str, *, label: str) -> None:
    if _NAME_RE.match(raw.strip()):
        return

    console.print(
        f"[red]x[/red] Nom de {label} invalide: [bold]{raw}[/bold]. "
        "Lettres, chiffres, _ et - uniquement. Doit commencer par une lettre."
    )
    raise typer.Exit(1)


def _assert_missing(path: Path, project_dir: Path) -> None:
    if not path.exists():
        return

    console.print(f"[red]x[/red] Le fichier existe deja: [bold]{path.relative_to(project_dir)}[/bold].")
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


def _strip_pascal_suffix(value: str, suffix: str) -> str:
    if value.endswith(suffix):
        return value[: -len(suffix)]
    return value


def _strip_snake_suffix(value: str) -> str:
    for suffix in ("_use_case", "_usecase"):
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value
