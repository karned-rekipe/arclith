from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .project_paths import detect_project_paths


@dataclass(frozen=True)
class EntityInfo:
    pascal: str   # Ingredient
    snake: str    # ingredient
    file_path: Path


def scan_entities(project_dir: Path) -> list[EntityInfo]:
    """Scan domain model files via AST to find Entity subclasses.

    Extracts any class that directly names 'Entity' as a base.
    Parsing errors are silently skipped so a broken file never blocks the wizard.
    """
    models_dir = detect_project_paths(project_dir).domain_models
    if not models_dir.exists():
        return []

    entities: list[EntityInfo] = []
    for py_file in sorted(models_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = {
                b.id if isinstance(b, ast.Name)
                else b.attr if isinstance(b, ast.Attribute)
                else ""
                for b in node.bases
            }
            if "Entity" in base_names:
                entities.append(EntityInfo(
                    pascal=node.name,
                    snake=_to_snake(node.name),
                    file_path=py_file,
                ))
    return entities


def scan_installed_adapters(project_dir: Path) -> list[str]:
    """Return adapter names found under adapters/output/ (subdirectory names)."""
    output_dir = detect_project_paths(project_dir).adapters_output
    if not output_dir.exists():
        return []
    return sorted(
        p.name for p in output_dir.iterdir()
        if p.is_dir() and not p.name.startswith("_")
    )


def _to_snake(pascal: str) -> str:
    import re
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", pascal)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower()
