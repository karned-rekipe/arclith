"""Resolve selected Python import origins without importing project code."""

import ast
import sys
from pathlib import Path

from arclith_cli.entity_contract_ast import module_imports
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


def project_absolute_import(
    paths: ProjectPaths,
    node: ast.ImportFrom,
    module: str,
) -> str:
    """Resolve an import while respecting package ``__init__`` semantics."""
    if not node.level:
        return absolute_import(node, module)
    source = _project_module_source(paths, module)
    is_package = source is not None and source[1]
    parts = module.split(".")
    retained = len(parts) - node.level + int(is_package)
    if retained <= 0:
        raise ValueError("Relative request import escapes its package")
    suffix = node.module.split(".") if node.module else []
    return ".".join((*parts[:retained], *suffix))


def project_imported_symbol(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    name: str,
) -> tuple[ast.Module, str, str] | None:
    """Resolve a directly imported symbol to project-owned source."""
    for statement in module_imports(tree):
        if not isinstance(statement, ast.ImportFrom):
            continue
        for alias in statement.names:
            if (alias.asname or alias.name) != name:
                continue
            imported_module = project_absolute_import(paths, statement, module)
            imported_name = alias.name
            if statement.module is None:
                imported_module = f"{imported_module}.{alias.name}"
            imported_tree = project_module_tree(paths, imported_module)
            if imported_tree is not None:
                return imported_tree, imported_module, imported_name
    return None


def project_qualified_imported_symbol(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    name: str,
) -> tuple[ast.Module, str, str] | None:
    """Resolve ``alias.Symbol`` to a project-owned module and declaration."""
    root, *tail = name.split(".")
    if not tail:
        return None
    imported_module: str | None = None
    for statement in module_imports(tree):
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                local = alias.asname or alias.name.split(".")[0]
                if local == root:
                    imported_module = alias.name if alias.asname else root
                    break
        elif isinstance(statement, ast.ImportFrom):
            for alias in statement.names:
                if (alias.asname or alias.name) == root:
                    parent = project_absolute_import(paths, statement, module)
                    imported_module = f"{parent}.{alias.name}"
                    break
        if imported_module is not None:
            break
    if imported_module is None:
        return None
    candidate_module = ".".join((imported_module, *tail[:-1]))
    imported_tree = project_module_tree(paths, candidate_module)
    if imported_tree is None:
        return None
    return imported_tree, candidate_module, tail[-1]


def uninspectable_external_reference(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    reference: str,
) -> bool:
    """Return whether an imported reference cannot be inspected statically."""
    return _uninspectable_external_reference(
        paths,
        tree,
        module,
        reference,
        visited=set(),
    )


def _uninspectable_external_reference(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    reference: str,
    *,
    visited: set[tuple[str, str]],
) -> bool:
    key = (module, reference)
    if key in visited:
        return False
    visited.add(key)
    project_reference = (
        project_qualified_imported_symbol(paths, tree, module, reference)
        if "." in reference
        else project_imported_symbol(paths, tree, module, reference)
    )
    if project_reference is not None:
        imported_tree, project_module, imported_name = project_reference
        return _uninspectable_external_reference(
            paths,
            imported_tree,
            project_module,
            imported_name,
            visited=visited,
        )
    root = reference.split(".", maxsplit=1)[0]
    imported_module: str | None = None
    for statement in module_imports(tree):
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                local = alias.asname or alias.name.split(".")[0]
                if local == root:
                    imported_module = alias.name
                    break
        elif isinstance(statement, ast.ImportFrom):
            for alias in statement.names:
                if (alias.asname or alias.name) == root:
                    imported_module = project_absolute_import(paths, statement, module)
                    break
        if imported_module is not None:
            break
    if imported_module is None or project_module_tree(paths, imported_module) is not None:
        return False
    external_root = imported_module.split(".", maxsplit=1)[0]
    return external_root not in {
        *sys.stdlib_module_names,
        "arclith",
        "pydantic",
        "typing_extensions",
    }


def pydantic_field_references(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Keep the local spelling of imports that originate from Pydantic."""
    return _pydantic_symbol_references(paths, tree, module, "Field")


def pydantic_field_info_references(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Keep local spellings of imports resolving to Pydantic FieldInfo."""
    return _pydantic_symbol_references(paths, tree, module, "FieldInfo")


def pydantic_base_model_references(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Keep local spellings of imports resolving to Pydantic BaseModel."""
    return _pydantic_symbol_references(paths, tree, module, "BaseModel")


def pydantic_alias_path_references(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Keep local spellings of imports resolving to Pydantic AliasPath."""
    return _pydantic_symbol_references(paths, tree, module, "AliasPath")


def pydantic_alias_choices_references(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Keep local spellings of imports resolving to Pydantic AliasChoices."""
    return _pydantic_symbol_references(paths, tree, module, "AliasChoices")


def _pydantic_symbol_references(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    symbol: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    names: set[str] = set()
    modules: set[str] = set()
    for statement in module_imports(tree):
        if isinstance(statement, ast.ImportFrom):
            imported_module = project_absolute_import(paths, statement, module)
            for alias in statement.names:
                local_name = alias.asname or alias.name
                if _is_pydantic_symbol(
                    paths,
                    imported_module,
                    alias.name,
                    target=symbol,
                    visited=set(),
                ):
                    names.add(local_name)
                else:
                    candidate_module = f"{imported_module}.{alias.name}"
                    inspectable_module = (
                        project_module_tree(
                            paths,
                            candidate_module,
                        )
                        is not None
                    )
                    if (
                        statement.module is None
                        or inspectable_module
                        or candidate_module in {"pydantic.fields", "pydantic.v1"}
                    ) and _module_exports_pydantic_symbol(
                        paths,
                        candidate_module,
                        symbol=symbol,
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
                        and _module_exports_pydantic_symbol(
                            paths,
                            alias.name,
                            symbol=symbol,
                            visited=set(),
                        )
                    )
                ):
                    modules.add(local_name)
    return tuple(sorted(names)), tuple(sorted(modules))


def _module_exports_pydantic_symbol(
    paths: ProjectPaths,
    module: str,
    *,
    symbol: str = "Field",
    visited: set[tuple[str, str]],
) -> bool:
    return _is_pydantic_symbol(
        paths,
        module,
        symbol,
        target=symbol,
        visited=visited,
    )


def project_module_tree(paths: ProjectPaths, module: str) -> ast.Module | None:
    """Return the syntax tree for a module owned by the generated project."""
    return _project_module_tree(paths, module)


def _is_pydantic_symbol(
    paths: ProjectPaths,
    module: str,
    symbol: str,
    *,
    target: str,
    visited: set[tuple[str, str]],
) -> bool:
    if module == "pydantic" or module.startswith("pydantic."):
        return symbol == target
    reference = (module, symbol)
    if reference in visited:
        return False
    visited.add(reference)
    source = _project_module_source(paths, module)
    if source is None:
        return False
    module_tree, _ = source
    for statement in module_imports(module_tree):
        if not isinstance(statement, ast.ImportFrom):
            continue
        imported_module = project_absolute_import(paths, statement, module)
        for alias in statement.names:
            if (alias.asname or alias.name) != symbol:
                continue
            return _is_pydantic_symbol(
                paths,
                imported_module,
                alias.name,
                target=target,
                visited=visited,
            )
    return False


def _project_module_tree(paths: ProjectPaths, module: str) -> ast.Module | None:
    source = _project_module_source(paths, module)
    return source[0] if source is not None else None


def _project_module_source(
    paths: ProjectPaths,
    module: str,
) -> tuple[ast.Module, bool] | None:
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
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            return tree, path.name == "__init__.py"
    return None
