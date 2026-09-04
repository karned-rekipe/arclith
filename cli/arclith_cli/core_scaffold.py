from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console

from .entity_scanner import EntityInfo, scan_entities
from .project_paths import ProjectPaths, detect_project_paths
from .rename import EntityNames
from .scaffold_templates import (
    render_entity_inbound_port_template,
    render_entity_template,
    render_entity_use_case_template,
    render_transverse_inbound_port_template,
    render_transverse_use_case_template,
)

console = Console()

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")

_INTENT_INTERPRETER_TEMPLATE = """class {class_name}Interpreter:
    async def interpret(self, prompt: str) -> None:
        raise NotImplementedError("Implement {class_name}Interpreter.interpret")
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
            console.print(
                f"[red]✗[/red] Nom de cas d'usage invalide : [bold]{raw}[/bold]."
            )
            raise typer.Exit(1)
        return cls(pascal=pascal, snake=snake)


@dataclass(frozen=True)
class IntentInterpreterNames:
    pascal: str
    snake: str

    @classmethod
    def from_input(cls, raw: str) -> IntentInterpreterNames:
        names = EntityNames.from_input(raw)
        pascal = _strip_pascal_intent_interpreter_suffix(names.pascal)
        snake = _strip_snake_intent_interpreter_suffix(names.snake)
        if not pascal or not snake:
            console.print(
                f"[red]✗[/red] Nom d'interpréteur d'intention invalide : [bold]{raw}[/bold]."
            )
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
    entity_file.write_text(
        render_entity_template(class_name=names.pascal), encoding="utf-8"
    )
    console.print(
        f"[green]✓[/green] Entité {names.pascal} créée : "
        f"[bold]{entity_file.relative_to(project_dir)}[/bold]"
    )
    return entity_file


def add_usecase_cmd(
    *,
    project_dir: Path | None = None,
    usecase_name: str,
    entity_name: str | None = None,
    new_entity_name: str | None = None,
) -> Path:
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
    entity = _resolve_usecase_entity(
        project_dir=project_dir,
        paths=paths,
        entity_name=entity_name,
        new_entity_name=new_entity_name,
    )

    _ensure_package_dirs(paths, "domain", "ports", "inbound")
    _ensure_package_dirs(paths, "application", "use_cases")
    inbound_port_module = paths.import_path("domain", "ports", "inbound", names.snake)
    if entity is None:
        inbound_port_content = render_transverse_inbound_port_template(
            class_name=names.pascal
        )
        usecase_content = render_transverse_use_case_template(
            class_name=names.pascal,
            inbound_port_module=inbound_port_module,
        )
    else:
        entity_module = paths.import_path(
            "domain",
            "models",
            entity.file_path.stem,
        )
        inbound_port_content = render_entity_inbound_port_template(
            class_name=names.pascal,
            entity_class=entity.pascal,
            entity_module=entity_module,
        )
        usecase_content = render_entity_use_case_template(
            class_name=names.pascal,
            entity_class=entity.pascal,
            entity_module=entity_module,
            inbound_port_module=inbound_port_module,
        )
    inbound_port_file.write_text(inbound_port_content, encoding="utf-8")
    usecase_file.write_text(usecase_content, encoding="utf-8")
    console.print(
        f"[green]✓[/green] Port inbound {names.pascal}Port créé : "
        f"[bold]{inbound_port_file.relative_to(project_dir)}[/bold]"
    )
    console.print(
        f"[green]✓[/green] Cas d'usage {names.pascal}UseCase créé : "
        f"[bold]{usecase_file.relative_to(project_dir)}[/bold]"
    )
    if entity is not None:
        console.print(
            f"[green]✓[/green] Entité principale : [bold]{entity.pascal}[/bold]"
        )
    return usecase_file


def _resolve_usecase_entity(
    *,
    project_dir: Path,
    paths: ProjectPaths,
    entity_name: str | None,
    new_entity_name: str | None,
) -> EntityInfo | None:
    if entity_name is not None and new_entity_name is not None:
        console.print(
            "[red]✗[/red] Une seule entité peut être choisie : "
            "utilisez [bold]entity_name[/bold] ou [bold]new_entity_name[/bold]."
        )
        raise typer.Exit(1)
    if entity_name is not None:
        return _require_existing_entity(project_dir, entity_name)
    if new_entity_name is None:
        return None

    raw_name = new_entity_name.strip()
    _assert_valid_name(raw_name, label="entité")
    names = EntityNames.from_input(raw_name)
    existing_entity = _find_entity(project_dir, names.pascal)
    if existing_entity is not None:
        return existing_entity

    expected_file = paths.domain_models / f"{names.snake}.py"
    if expected_file.exists():
        console.print(
            f"[red]✗[/red] Le fichier [bold]{expected_file.relative_to(project_dir)}[/bold] "
            f"existe mais ne déclare pas [bold]class {names.pascal}(Entity)[/bold]."
        )
        raise typer.Exit(1)

    add_entity_cmd(project_dir=project_dir, entity_name=raw_name)
    created_entity = _find_entity(project_dir, names.pascal)
    if (
        created_entity is None
    ):  # pragma: no cover - defensive check after our own template
        console.print(
            f"[red]✗[/red] Impossible de détecter l'entité créée {names.pascal}."
        )
        raise typer.Exit(1)
    return created_entity


def _require_existing_entity(project_dir: Path, raw_name: str) -> EntityInfo:
    normalized_name = raw_name.strip()
    _assert_valid_name(normalized_name, label="entité")
    names = EntityNames.from_input(normalized_name)
    entities = scan_entities(project_dir)
    entity = next(
        (item for item in entities if item.pascal == names.pascal),
        None,
    )
    if entity is not None:
        return entity

    detected = ", ".join(item.pascal for item in entities) or "aucune"
    console.print(
        f"[red]✗[/red] Entité introuvable : [bold]{names.pascal}[/bold]. "
        f"Entités détectées : {detected}. Utilisez [bold]--new-entity {names.pascal}[/bold] "
        "pour la créer."
    )
    raise typer.Exit(1)


def _find_entity(project_dir: Path, pascal_name: str) -> EntityInfo | None:
    return next(
        (
            entity
            for entity in scan_entities(project_dir)
            if entity.pascal == pascal_name
        ),
        None,
    )


def add_intent_interpreter_cmd(
    *, project_dir: Path | None = None, intent_name: str
) -> Path:
    project_dir = project_dir or Path.cwd()
    intent_name = intent_name.strip()
    _assert_project_root(project_dir, command="add-intent-interpreter")
    _assert_valid_name(intent_name, label="interpréteur d'intention")

    paths = detect_project_paths(project_dir)
    names = IntentInterpreterNames.from_input(intent_name)
    intent_file = paths.application_intent_interpreters / f"{names.snake}.py"
    _assert_missing(intent_file, project_dir)

    _ensure_package_dirs(paths, "application", "intent_interpreters")
    intent_file.write_text(
        _INTENT_INTERPRETER_TEMPLATE.format(class_name=names.pascal), encoding="utf-8"
    )
    console.print(
        f"[green]✓[/green] Interpréteur d'intention {names.pascal}Interpreter créé : "
        f"[bold]{intent_file.relative_to(project_dir)}[/bold]"
    )
    return intent_file


def _assert_project_root(project_dir: Path, *, command: str) -> None:
    if not project_dir.exists() or not project_dir.is_dir():
        console.print(
            f"[red]✗[/red] Répertoire introuvable : [bold]{project_dir}[/bold]."
        )
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

    console.print(
        f"[red]✗[/red] Le fichier existe déjà : [bold]{path.relative_to(project_dir)}[/bold]."
    )
    raise typer.Exit(1)


def _ensure_package_dirs(paths: ProjectPaths, *relative_parts: str) -> None:
    target_dir = paths.package_root.joinpath(*relative_parts)
    target_dir.mkdir(parents=True, exist_ok=True)

    stop_at = (
        paths.package_root.parent
        if paths.package_name is not None
        else paths.package_root
    )
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


def _strip_pascal_intent_interpreter_suffix(value: str) -> str:
    suffixes = ("Interpreter",)
    while True:
        stripped = value
        for suffix in suffixes:
            if stripped.endswith(suffix):
                stripped = stripped[: -len(suffix)]
                break
        if stripped == value:
            return value
        value = stripped


def _strip_snake_intent_interpreter_suffix(value: str) -> str:
    suffixes = ("_interpreter",)
    while True:
        stripped = value
        for suffix in suffixes:
            if stripped.endswith(suffix):
                stripped = stripped[: -len(suffix)]
                break
        if stripped == value:
            return value
        value = stripped
