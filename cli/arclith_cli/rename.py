from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_SOURCE_PASCAL = "Ingredient"
_SOURCE_SNAKE = "ingredient"
_SOURCE_UPPER = "INGREDIENT"
_SOURCE_PACKAGE = "arclith_sample"

_TEXT_EXTENSIONS = {
    ".py", ".yaml", ".yml", ".toml", ".md", ".txt", ".json",
    ".cfg", ".ini", ".env", ".sh", ".rst",
}


@dataclass(frozen=True)
class EntityNames:
    pascal: str  # RecipeStep
    snake: str   # recipe_step
    upper: str   # RECIPE_STEP

    @classmethod
    def from_input(cls, raw: str) -> "EntityNames":
        pascal = _to_pascal(raw)
        snake = _to_snake(raw)
        return cls(pascal=pascal, snake=snake, upper=snake.upper())


def apply_rename(target_dir: Path, names: EntityNames, *, project_name: str, port: int) -> None:
    package_name = _to_package(project_name)
    _rename_file_contents(target_dir, names, package_name)
    _rename_paths(target_dir, names, package_name)
    _patch_pyproject(target_dir, project_name)
    _patch_config(target_dir, project_name, port)


# ── Content replacement ───────────────────────────────────────────────────────

def _replace_in_text(text: str, names: EntityNames, package_name: str) -> str:
    # Order: most specific first to avoid partial overlap (UPPER before lower)
    return (
        text
        .replace(_SOURCE_UPPER, names.upper)
        .replace(_SOURCE_PASCAL, names.pascal)
        .replace(_SOURCE_SNAKE, names.snake)
        .replace(_SOURCE_PACKAGE, package_name)
    )


def _rename_file_contents(directory: Path, names: EntityNames, package_name: str) -> None:
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _TEXT_EXTENSIONS and path.suffix != "":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        new_text = _replace_in_text(text, names, package_name)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")


# ── Path renaming ─────────────────────────────────────────────────────────────

def _rename_paths(directory: Path, names: EntityNames, package_name: str) -> None:
    # Deepest first so parent renames don't invalidate children
    candidates = sorted(
        directory.rglob("*"),
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for path in candidates:
        if not path.exists():
            continue
        if not any(tok in path.name for tok in (_SOURCE_SNAKE, _SOURCE_PASCAL, _SOURCE_UPPER, _SOURCE_PACKAGE)):
            continue
        new_name = _replace_in_text(path.name, names, package_name)
        if new_name != path.name:
            path.rename(path.parent / new_name)


# ── pyproject.toml patching ───────────────────────────────────────────────────

def _patch_pyproject(target_dir: Path, project_name: str) -> None:
    p = target_dir / "pyproject.toml"
    if not p.exists():
        return
    text = p.read_text(encoding="utf-8")
    # Update project name (first occurrence)
    text = re.sub(r'(?m)^name\s*=\s*"[^"]*"', f'name = "{project_name}"', text, count=1)
    text = _patch_arclith_dependency(text)
    # Remove [tool.uv.sources] block (editable arclith path)
    text = re.sub(
        r"\[tool\.uv\.sources\]\n(?:[^\[]*)",
        "",
        text,
        flags=re.DOTALL,
    )
    p.write_text(text.strip() + "\n", encoding="utf-8")


def _patch_arclith_dependency(text: str) -> str:
    framework_version = _installed_arclith_version()
    if framework_version is None:
        return text
    return re.sub(
        r'("arclith(?:\[[^"]+\])?>=)[^"]+(")',
        lambda match: f"{match.group(1)}{framework_version}{match.group(2)}",
        text,
        count=1,
    )


def _installed_arclith_version() -> str | None:
    try:
        return version("arclith")
    except PackageNotFoundError:
        return None


# ── config/ directory patching ────────────────────────────────────────────────

def _patch_config(target_dir: Path, project_name: str, port: int) -> None:
    _patch_yaml_field(target_dir / "config" / "app.yaml", "name", project_name)
    _patch_yaml_field(
        target_dir / "config" / "app.yaml",
        "description",
        f'"{project_name} — built on arclith"',
    )
    _patch_yaml_field(
        target_dir / "config" / "adapters" / "outbound" / "mongodb.yaml",
        "db_name",
        project_name,
    )
    _patch_section_port(
        target_dir / "config" / "adapters" / "inbound" / "fastapi.yaml",
        port,
    )
    _patch_section_port(
        target_dir / "config" / "adapters" / "inbound" / "fastmcp.yaml",
        port + 1,
    )


def _patch_yaml_field(path: Path, key: str, value: str) -> None:
    if not path.exists():
        return
    text = path.read_text()
    text = re.sub(rf"(?m)(^{re.escape(key)}:\s*).*$", rf"\g<1>{value}", text, count=1)
    path.write_text(text)


def _patch_section_port(path: Path, new_port: int) -> None:
    if not path.exists():
        return
    text = path.read_text()
    text = re.sub(r"(?m)(^port:\s*)\d+", rf"\g<1>{new_port}", text, count=1)
    path.write_text(text)


# ── Case converters ───────────────────────────────────────────────────────────

def _to_pascal(raw: str) -> str:
    if "_" in raw or "-" in raw:
        return "".join(w.capitalize() for w in re.split(r"[_\-]", raw) if w)
    return raw[0].upper() + raw[1:] if raw else raw


def _to_snake(raw: str) -> str:
    if "_" in raw:
        return raw.lower()
    if "-" in raw:
        return raw.replace("-", "_").lower()
    # PascalCase / camelCase → snake_case
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", raw)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower()


def _to_package(raw: str) -> str:
    package = raw.replace("-", "_").lower()
    package = re.sub(r"[^a-z0-9_]", "_", package)
    package = re.sub(r"_+", "_", package).strip("_")
    if not package or not package[0].isalpha():
        raise ValueError(f"Invalid project name for Python package: {raw!r}")
    return package
