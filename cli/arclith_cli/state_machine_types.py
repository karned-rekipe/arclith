"""Resolve state-machine field types without importing project-owned code."""

from __future__ import annotations

import ast
from pathlib import Path

from arclith_cli.module_bindings import (
    module_bindings_before,
    node_line_or_module_end,
    uncertain_module_bindings_before,
)


def resolve_literal_values(
    annotation: ast.expr,
    *,
    tree: ast.Module,
    entity_file: Path,
    visited: frozenset[tuple[Path, str]] = frozenset(),
) -> set[str] | None:
    """Resolve a Literal annotation or alias to its static string values."""

    if isinstance(annotation, ast.Subscript):
        if not is_imported_symbol(
            annotation.value,
            symbols=frozenset({"Literal"}),
            modules=frozenset({"typing", "typing_extensions"}),
            tree=tree,
        ):
            return None
        values = (
            annotation.slice.elts
            if isinstance(annotation.slice, ast.Tuple)
            else (annotation.slice,)
        )
        literal_states = {
            value.value
            for value in values
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        }
        return literal_states if len(literal_states) == len(values) else None
    if not isinstance(annotation, ast.Name):
        return None
    key = (entity_file, annotation.id)
    if key in visited:
        return None
    if annotation.id in uncertain_module_bindings_before(
        tree,
        node_line_or_module_end(annotation, tree),
    ):
        return None
    bindings = _top_level_bindings_before(tree, annotation.id, annotation)
    if len(bindings) != 1:
        return None
    binding = bindings[0]
    alias_value = _alias_value(binding, annotation.id)
    if alias_value is not None:
        return resolve_literal_values(
            alias_value,
            tree=tree,
            entity_file=entity_file,
            visited=visited | {key},
        )
    if not isinstance(binding, ast.ImportFrom):
        return None
    imported = next(
        (item for item in binding.names if (item.asname or item.name) == annotation.id),
        None,
    )
    module_file = _resolve_module_file(entity_file, binding)
    if imported is None or module_file is None:
        return None
    try:
        imported_tree = ast.parse(
            module_file.read_text(encoding="utf-8"),
            filename=str(module_file),
        )
    except (OSError, SyntaxError):
        return None
    return resolve_literal_values(
        ast.Name(id=imported.name),
        tree=imported_tree,
        entity_file=module_file,
        visited=visited | {key},
    )


def resolve_enum_values(
    annotation: ast.expr,
    *,
    tree: ast.Module,
    entity_file: Path,
    visited: frozenset[tuple[Path, str]] = frozenset(),
) -> set[str] | None:
    """Resolve an Enum annotation to its static string values."""

    resolved = resolve_enum_declaration(
        annotation,
        tree=tree,
        entity_file=entity_file,
        visited=visited,
    )
    if resolved is None:
        return None
    declaration, declaration_tree, _ = resolved
    return _enum_values(declaration, declaration_tree)


def resolve_enum_declaration(
    annotation: ast.expr,
    *,
    tree: ast.Module,
    entity_file: Path,
    visited: frozenset[tuple[Path, str]] = frozenset(),
) -> tuple[ast.ClassDef, ast.Module, Path] | None:
    """Resolve an Enum class available before the annotation use."""

    if not isinstance(annotation, ast.Name):
        return None
    symbol = annotation.id
    key = (entity_file, symbol)
    if key in visited:
        return None
    if symbol in uncertain_module_bindings_before(
        tree,
        node_line_or_module_end(annotation, tree),
    ):
        return None
    bindings = _top_level_bindings_before(tree, symbol, annotation)
    if len(bindings) != 1:
        return None
    binding = bindings[0]
    if isinstance(binding, ast.ClassDef):
        if _enum_values(binding, tree) is None:
            return None
        return binding, tree, entity_file
    alias_value = _alias_value(binding, symbol)
    if alias_value is not None:
        return resolve_enum_declaration(
            alias_value,
            tree=tree,
            entity_file=entity_file,
            visited=visited | {key},
        )
    if not isinstance(binding, ast.ImportFrom):
        return None
    imported = next(
        (item for item in binding.names if (item.asname or item.name) == symbol),
        None,
    )
    module_file = _resolve_module_file(entity_file, binding)
    if imported is None or module_file is None:
        return None
    try:
        imported_tree = ast.parse(
            module_file.read_text(encoding="utf-8"),
            filename=str(module_file),
        )
    except (OSError, SyntaxError):
        return None
    return resolve_enum_declaration(
        ast.Name(id=imported.name),
        tree=imported_tree,
        entity_file=module_file,
        visited=visited | {key},
    )


def enum_members(
    declaration: ast.ClassDef,
    tree: ast.Module,
) -> dict[str, str] | None:
    """Return exact static string members for a trusted Enum declaration."""

    if declaration.decorator_list:
        return None
    if not any(
        is_imported_symbol(
            base,
            symbols=frozenset({"Enum", "StrEnum"}),
            modules=frozenset({"enum"}),
            tree=tree,
        )
        for base in declaration.bases
    ):
        return None
    members: dict[str, str] = {}
    declarations: set[str] = set()
    for statement in declaration.body:
        if isinstance(statement, ast.Pass) or (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Enum hooks and arbitrary methods can mutate ``_value_`` or alter
            # runtime resolution. Their effects cannot be proven from the
            # static member assignments, so the exact-value contract fails
            # closed for declarations containing executable methods.
            return None
        member_name: str | None = None
        value: ast.expr | None = None
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            member_name = statement.targets[0].id
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            member_name = statement.target.id
            value = statement.value
        if member_name is None or member_name.startswith("_"):
            return None
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            return None
        if member_name in declarations:
            return None
        declarations.add(member_name)
        members[member_name] = value.value
    return members or None


def is_imported_symbol(
    expression: ast.expr,
    *,
    symbols: frozenset[str],
    modules: frozenset[str],
    tree: ast.Module,
) -> bool:
    """Prove that an expression resolves to a direct trusted import."""

    if isinstance(expression, ast.Name):
        binding = module_bindings_before(
            tree,
            node_line_or_module_end(expression, tree),
        ).get(expression.id)
        if binding is None:
            return False
        statement, alias = binding
        return (
            isinstance(statement, ast.ImportFrom)
            and statement in tree.body
            and statement.level == 0
            and statement.module in modules
            and alias.name in symbols
            and (alias.asname or alias.name) == expression.id
        )
    if not (
        isinstance(expression, ast.Attribute)
        and expression.attr in symbols
        and isinstance(expression.value, ast.Name)
    ):
        return False
    module_alias = expression.value.id
    binding = module_bindings_before(
        tree,
        node_line_or_module_end(expression, tree),
    ).get(module_alias)
    if binding is None:
        return False
    statement, alias = binding
    return (
        isinstance(statement, ast.Import)
        and statement in tree.body
        and alias.name in modules
        and (alias.asname or alias.name) == module_alias
    )


def _enum_values(declaration: ast.ClassDef, tree: ast.Module) -> set[str] | None:
    members = enum_members(declaration, tree)
    return set(members.values()) if members is not None else None


def _resolve_module_file(entity_file: Path, statement: ast.ImportFrom) -> Path | None:
    module_parts = statement.module.split(".") if statement.module else []
    if statement.level:
        base = entity_file.parent
        for _ in range(statement.level - 1):
            base = base.parent
        candidate = base.joinpath(*module_parts).with_suffix(".py")
        return candidate if candidate.is_file() else None
    for ancestor in entity_file.parents:
        candidate = ancestor.joinpath(*module_parts).with_suffix(".py")
        if candidate.is_file():
            return candidate
    return None


def _top_level_bindings_before(
    tree: ast.Module,
    symbol: str,
    reference: ast.AST,
) -> list[ast.stmt]:
    boundary = node_line_or_module_end(reference, tree)
    return [
        statement
        for statement in tree.body
        if statement.lineno < boundary and symbol in _bound_names(statement)
    ]


def _bound_names(statement: ast.stmt) -> set[str]:
    if isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return {statement.name}
    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        return {item.asname or item.name.split(".", 1)[0] for item in statement.names}
    if isinstance(statement, ast.Assign):
        return {
            target.id for target in statement.targets if isinstance(target, ast.Name)
        }
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        return {statement.target.id}
    if isinstance(statement, ast.TypeAlias) and isinstance(statement.name, ast.Name):
        return {statement.name.id}
    return set()


def _alias_value(statement: ast.stmt, symbol: str) -> ast.expr | None:
    if isinstance(statement, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == symbol
        for target in statement.targets
    ):
        return statement.value
    if (
        isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and statement.target.id == symbol
    ):
        return statement.value
    if (
        isinstance(statement, ast.TypeAlias)
        and isinstance(statement.name, ast.Name)
        and statement.name.id == symbol
    ):
        return statement.value
    return None
