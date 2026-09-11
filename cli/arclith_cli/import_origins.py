"""Resolve selected Python import origins without importing project code."""

import ast
from pathlib import Path

from arclith_cli.project_paths import ProjectPaths


def absolute_import(node: ast.ImportFrom, module: str) -> str:
    if not node.level:
        if node.module is None:
            raise ValueError("Imported symbol has no module")
        return node.module
    prefix = module.split(".")[: -node.level]
    if not prefix:
        raise ValueError("Relative request import escapes its package")
    suffix = node.module.split(".") if node.module else []
    return ".".join((*prefix, *suffix))


def pydantic_field_references(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Keep the local spelling of imports that originate from Pydantic."""
    names: set[str] = set()
    modules: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom):
            imported_module = absolute_import(statement, module)
            for alias in statement.names:
                local_name = alias.asname or alias.name
                if _is_pydantic_field(
                    paths, imported_module, alias.name, visited=set()
                ):
                    names.add(local_name)
                elif statement.module is None and _module_exports_pydantic_field(
                    paths,
                    f"{imported_module}.{alias.name}",
                    visited=set(),
                ):
                    modules.add(local_name)
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                local_name = alias.asname or alias.name.split(".")[0]
                if (
                    alias.name == "pydantic"
                    or alias.name.startswith("pydantic.")
                    or (
                        alias.asname is not None
                        and _module_exports_pydantic_field(
                            paths, alias.name, visited=set()
                        )
                    )
                ):
                    modules.add(local_name)
    return tuple(sorted(names)), tuple(sorted(modules))


def _module_exports_pydantic_field(
    paths: ProjectPaths,
    module: str,
    *,
    visited: set[tuple[str, str]],
) -> bool:
    return _is_pydantic_field(paths, module, "Field", visited=visited)


def _is_pydantic_field(
    paths: ProjectPaths,
    module: str,
    symbol: str,
    *,
    visited: set[tuple[str, str]],
) -> bool:
    if module == "pydantic" or module.startswith("pydantic."):
        return symbol == "Field"
    reference = (module, symbol)
    if reference in visited:
        return False
    visited.add(reference)
    module_tree = _project_module_tree(paths, module)
    if module_tree is None:
        return False
    for statement in module_tree.body:
        if not isinstance(statement, ast.ImportFrom):
            continue
        imported_module = absolute_import(statement, module)
        for alias in statement.names:
            if (alias.asname or alias.name) != symbol:
                continue
            return _is_pydantic_field(
                paths,
                imported_module,
                alias.name,
                visited=visited,
            )
    return False


def _project_module_tree(paths: ProjectPaths, module: str) -> ast.Module | None:
    package_name = paths.package_name
    if package_name is not None:
        if module == package_name:
            relative = Path()
        elif module.startswith(package_name + "."):
            relative = Path(*module.removeprefix(package_name + ".").split("."))
        else:
            return None
    else:
        relative = Path(*module.split("."))
    candidates = (
        paths.package_root / relative.with_suffix(".py"),
        paths.package_root / relative / "__init__.py",
    )
    for path in candidates:
        if path.is_file():
            return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return None
