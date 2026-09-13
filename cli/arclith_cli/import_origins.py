"""Resolve selected Python import origins without importing project code."""

import ast
import sys
from pathlib import Path

from arclith_cli.module_bindings import (
    conditional_module_bindings,
    module_bindings_before,
)
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
    *,
    before_line: int | None = None,
) -> tuple[ast.Module, str, str] | None:
    """Resolve a directly imported symbol to project-owned source."""
    binding = _active_import_binding(tree, name, before_line=before_line)
    if binding is None:
        return None
    statement, alias = binding
    if not isinstance(statement, ast.ImportFrom):
        return None
    imported_module = project_absolute_import(paths, statement, module)
    imported_name = alias.name
    if statement.module is None:
        package_tree = project_module_tree(paths, imported_module)
        if package_tree is not None and _module_binds_name(
            package_tree,
            alias.name,
        ):
            return package_tree, imported_module, imported_name
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
    *,
    before_line: int | None = None,
) -> tuple[ast.Module, str, str] | None:
    """Resolve ``alias.Symbol`` to a project-owned module and declaration."""
    root, *tail = name.split(".")
    if not tail:
        return None
    binding = _active_import_binding(tree, root, before_line=before_line)
    if binding is None:
        return None
    statement, alias = binding
    if isinstance(statement, ast.Import):
        imported_module = alias.name if alias.asname else root
    else:
        parent = project_absolute_import(paths, statement, module)
        imported_module = f"{parent}.{alias.name}"
    candidate_module = ".".join((imported_module, *tail[:-1]))
    imported_tree = project_module_tree(paths, candidate_module)
    if imported_tree is None:
        return None
    return imported_tree, candidate_module, tail[-1]


def _active_import_binding(
    tree: ast.Module,
    name: str,
    *,
    before_line: int | None = None,
) -> tuple[ast.Import | ast.ImportFrom, ast.alias] | None:
    if before_line is None:
        before_line = (
            max(
                (getattr(statement, "lineno", 0) for statement in ast.walk(tree)),
                default=0,
            )
            + 1
        )
    binding = module_bindings_before(tree, before_line).get(name)
    return binding if binding is not None else None


def uninspectable_external_reference(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    reference: str,
    *,
    before_line: int | None = None,
) -> bool:
    """Return whether an imported reference cannot be inspected statically."""
    return _uninspectable_external_reference(
        paths,
        tree,
        module,
        reference,
        visited=set(),
        before_line=before_line,
    )


def _uninspectable_external_reference(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    reference: str,
    *,
    visited: set[tuple[str, str]],
    before_line: int | None,
) -> bool:
    key = (module, reference)
    if key in visited:
        return False
    visited.add(key)
    project_reference = (
        project_qualified_imported_symbol(
            paths,
            tree,
            module,
            reference,
            before_line=before_line,
        )
        if "." in reference
        else project_imported_symbol(
            paths,
            tree,
            module,
            reference,
            before_line=before_line,
        )
    )
    if project_reference is not None:
        imported_tree, project_module, imported_name = project_reference
        return _uninspectable_external_reference(
            paths,
            imported_tree,
            project_module,
            imported_name,
            visited=visited,
            before_line=None,
        )
    root = reference.split(".", maxsplit=1)[0]
    binding = _active_import_binding(tree, root, before_line=before_line)
    imported_module: str | None = None
    if binding is not None:
        statement, alias = binding
        imported_module = (
            alias.name
            if isinstance(statement, ast.Import)
            else project_absolute_import(paths, statement, module)
        )
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
    *,
    before_line: int | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Keep the local spelling of imports that originate from Pydantic."""
    return _pydantic_symbol_references(
        paths,
        tree,
        module,
        "Field",
        before_line=before_line,
    )


def pydantic_field_info_references(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    *,
    before_line: int | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Keep local spellings of imports resolving to Pydantic FieldInfo."""
    return _pydantic_symbol_references(
        paths,
        tree,
        module,
        "FieldInfo",
        before_line=before_line,
    )


def pydantic_base_model_references(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    *,
    before_line: int | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Keep local spellings of imports resolving to Pydantic BaseModel."""
    return _pydantic_symbol_references(
        paths,
        tree,
        module,
        "BaseModel",
        before_line=before_line,
    )


def pydantic_config_dict_references(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    *,
    before_line: int | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Keep local spellings of imports resolving to Pydantic ConfigDict."""
    return _pydantic_symbol_references(
        paths,
        tree,
        module,
        "ConfigDict",
        before_line=before_line,
    )


def pydantic_alias_path_references(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    *,
    before_line: int | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Keep local spellings of imports resolving to Pydantic AliasPath."""
    return _pydantic_symbol_references(
        paths,
        tree,
        module,
        "AliasPath",
        before_line=before_line,
    )


def pydantic_alias_choices_references(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    *,
    before_line: int | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Keep local spellings of imports resolving to Pydantic AliasChoices."""
    return _pydantic_symbol_references(
        paths,
        tree,
        module,
        "AliasChoices",
        before_line=before_line,
    )


def _pydantic_symbol_references(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    symbol: str,
    *,
    before_line: int | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    names, modules = _module_pydantic_bindings(
        paths,
        tree,
        module,
        symbol,
        visited=set(),
        before_line=before_line,
    )
    return tuple(sorted(names)), tuple(sorted(modules))


def _module_pydantic_bindings(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    symbol: str,
    *,
    visited: set[tuple[str, str]],
    before_line: int | None,
) -> tuple[set[str], set[str]]:
    names: set[str] = set()
    modules: set[str] = set()

    def clear(name: str) -> None:
        names.discard(name)
        modules.discard(name)

    events: list[tuple[int, int, ast.stmt | str]] = [
        (statement.lineno, statement.col_offset, statement)
        for statement in tree.body
    ]
    events.extend(conditional_module_bindings(tree))
    for line, _, statement in sorted(events, key=lambda item: item[:2]):
        if before_line is not None and line > before_line:
            continue
        if isinstance(statement, str):
            clear(statement)
            continue
        if isinstance(statement, ast.ImportFrom):
            imported_module = project_absolute_import(paths, statement, module)
            for alias in statement.names:
                local_name = alias.asname or alias.name
                clear(local_name)
                if _is_pydantic_symbol(
                    paths,
                    imported_module,
                    alias.name,
                    target=symbol,
                    visited=set(visited),
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
                        visited=set(visited),
                    ):
                        modules.add(local_name)
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                local_name = alias.asname or alias.name.split(".")[0]
                clear(local_name)
                if (
                    alias.name == "pydantic"
                    or alias.name.startswith("pydantic.")
                    or (
                        alias.asname is not None
                        and _module_exports_pydantic_symbol(
                            paths,
                            alias.name,
                            symbol=symbol,
                            visited=set(visited),
                        )
                    )
                ):
                    modules.add(local_name)
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            value: ast.expr | None
            if isinstance(statement, ast.Assign):
                targets = [
                    target.id
                    for target in statement.targets
                    if isinstance(target, ast.Name)
                ]
                value = statement.value
            elif isinstance(statement.target, ast.Name):
                targets = [statement.target.id]
                value = statement.value
            else:
                continue
            symbol_alias = value is not None and _references_pydantic_symbol(
                value,
                names,
                modules,
                symbol,
            )
            module_alias = isinstance(value, ast.Name) and value.id in modules
            for target in targets:
                clear(target)
                if symbol_alias:
                    names.add(target)
                elif module_alias:
                    modules.add(target)
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            clear(statement.name)
    return names, modules


def _references_pydantic_symbol(
    value: ast.expr,
    names: set[str],
    modules: set[str],
    symbol: str,
) -> bool:
    return (isinstance(value, ast.Name) and value.id in names) or (
        isinstance(value, ast.Attribute)
        and value.attr == symbol
        and _root_name(value.value) in modules
    )


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


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
    names, _ = _module_pydantic_bindings(
        paths,
        module_tree,
        module,
        target,
        visited=visited,
        before_line=None,
    )
    return symbol in names


def _module_binds_name(tree: ast.Module, name: str) -> bool:
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom) and any(
            (alias.asname or alias.name) == name for alias in statement.names
        ):
            return True
        if isinstance(statement, ast.Import) and any(
            (alias.asname or alias.name.split(".")[0]) == name
            for alias in statement.names
        ):
            return True
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if statement.name == name:
                return True
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        ):
            return True
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == name
        ):
            return True
        if (
            isinstance(statement, ast.TypeAlias)
            and isinstance(statement.name, ast.Name)
            and statement.name.id == name
        ):
            return True
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
