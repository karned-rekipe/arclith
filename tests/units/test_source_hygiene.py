from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[2]
SOURCE_ROOTS = (PROJECT_ROOT / "arclith", PROJECT_ROOT / "cli" / "arclith_cli")
DEFINITION_NODES = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
MAX_SOURCE_LINES = 600


def _python_files() -> list[Path]:
    return sorted(path for root in SOURCE_ROOTS for path in root.rglob("*.py"))


@pytest.mark.parametrize(
    "package_dir",
    sorted({path.parent for path in _python_files()}),
    ids=lambda path: str(path),
)
def test_python_source_directories_are_importable_packages(package_dir: Path) -> None:
    assert (package_dir / "__init__.py").is_file(), (
        f"{package_dir} contains Python modules but has no __init__.py; "
        "zipimport cannot reliably load it from the wheel"
    )


def _is_overload(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        (isinstance(decorator, ast.Name) and decorator.id == "overload")
        or (isinstance(decorator, ast.Attribute) and decorator.attr == "overload")
        for decorator in node.decorator_list
    )


@pytest.mark.parametrize("path", _python_files(), ids=lambda path: str(path))
def test_source_has_no_unintentional_duplicate_definitions(path: Path) -> None:
    """Prevent silent shadowing while preserving standard typing overload sets."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    scopes: list[ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef] = [
        tree,
        *(node for node in ast.walk(tree) if isinstance(node, DEFINITION_NODES)),
    ]

    duplicates: list[str] = []
    for scope in scopes:
        definitions: dict[
            str, list[ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef]
        ] = defaultdict(list)
        for node in scope.body:
            if isinstance(node, DEFINITION_NODES):
                definitions[node.name].append(node)
        scope_name = getattr(scope, "name", "<module>")
        for name, nodes in definitions.items():
            if len(nodes) == 1:
                continue
            if all(_is_overload(node) for node in nodes[:-1]) and not _is_overload(
                nodes[-1]
            ):
                continue
            duplicates.append(
                f"{scope_name}.{name} at lines {[node.lineno for node in nodes]}"
            )

    assert not duplicates, (
        f"Unintentional duplicate definitions in {path}: {duplicates}"
    )


@pytest.mark.parametrize("path", _python_files(), ids=lambda path: str(path))
def test_classes_have_no_duplicate_fields(path: Path) -> None:
    """Catch repeated annotated fields, which Python otherwise overwrites silently."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    duplicates: list[str] = []

    for class_node in (
        node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    ):
        fields: dict[str, list[int]] = defaultdict(list)
        for node in class_node.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                fields[node.target.id].append(node.lineno)
        duplicates.extend(
            f"{class_node.name}.{name} at lines {lines}"
            for name, lines in fields.items()
            if len(lines) > 1
        )

    assert not duplicates, f"Duplicate fields in {path}: {duplicates}"


@pytest.mark.parametrize("path", _python_files(), ids=lambda path: str(path))
def test_source_modules_remain_focused(path: Path) -> None:
    line_count = len(path.read_text(encoding="utf-8").splitlines())

    assert line_count <= MAX_SOURCE_LINES, (
        f"{path} has {line_count} lines; split responsibilities before it exceeds "
        f"{MAX_SOURCE_LINES} lines"
    )


@pytest.mark.parametrize("path", _python_files(), ids=lambda path: str(path))
def test_source_has_no_adjacent_duplicate_statements(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    duplicates: list[str] = []

    for parent in ast.walk(tree):
        for field_name in ("body", "orelse", "finalbody"):
            statements = getattr(parent, field_name, None)
            if not isinstance(statements, list):
                continue
            for left, right in zip(statements, statements[1:], strict=False):
                if ast.dump(left, include_attributes=False) == ast.dump(
                    right, include_attributes=False
                ):
                    duplicates.append(
                        f"identical statements at lines {left.lineno} and {right.lineno}"
                    )

    assert not duplicates, f"Adjacent duplicate statements in {path}: {duplicates}"
