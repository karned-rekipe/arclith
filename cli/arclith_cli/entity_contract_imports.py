"""Snapshot imports and safe constants required by projected entity fields."""

from __future__ import annotations

import ast
import builtins
from collections.abc import Callable

from arclith_cli.entity_contract_ast import field_dependencies, module_bindings_before
from arclith_cli.import_origins import absolute_import


def field_imports(
    tree: ast.Module,
    fields: tuple[ast.AnnAssign, ...],
    module: str,
    typing_kind: Callable[[ast.expr], str | None],
    *,
    before_line: int,
) -> tuple[str, ...]:
    """Render dependencies with declaration-time semantics."""
    used = field_dependencies(fields, typing_kind)
    bindings = module_bindings_before(tree, before_line)
    resolved = set(dir(builtins)) - bindings.keys()
    imports: list[str] = []
    import_bindings: dict[int, tuple[ast.Import | ast.ImportFrom, list[ast.alias]]] = {}
    local: list[str] = []
    for name in sorted(used & bindings.keys()):
        binding = bindings[name]
        if binding is None:
            local.append(name)
            continue
        statement, alias = binding
        import_bindings.setdefault(id(statement), (statement, []))[1].append(alias)
    for statement, aliases in import_bindings.values():
        selected = sorted(
            aliases,
            key=lambda alias: alias.asname or alias.name.split(".")[0],
        )
        if isinstance(statement, ast.ImportFrom):
            rendered: ast.Import | ast.ImportFrom = ast.ImportFrom(
                module=absolute_import(statement, module),
                names=selected,
                level=0,
            )
        else:
            rendered = ast.Import(names=selected)
        imports.append(ast.unparse(rendered))
        resolved.update(
            alias.asname or alias.name.split(".")[0] for alias in selected
        )

    imported_local: list[str] = []
    for name in local:
        snapshot = _local_literal_snapshot(tree, name, before_line)
        if snapshot is not None:
            imports.append(snapshot)
        elif _module_name_rebound_after(tree, name, before_line):
            raise ValueError(
                f"Entity dependency {name!r} is rebound after the model declaration; "
                "inline a stable declaration before generating CRUD contracts"
            )
        else:
            imported_local.append(name)
        resolved.add(name)
    if imported_local:
        imports.append(f"from {module} import {', '.join(imported_local)}")

    unresolved = used - resolved
    if unresolved:
        raise ValueError(
            "Unresolved entity field dependencies cannot be projected into CRUD "
            "commands: " + ", ".join(sorted(unresolved))
        )
    return tuple(imports)


def _local_literal_snapshot(
    tree: ast.Module,
    name: str,
    before_line: int,
) -> str | None:
    statement = next(
        (
            candidate
            for candidate in reversed(tree.body)
            if candidate.lineno <= before_line
            and _statement_binds(candidate, name)
        ),
        None,
    )
    value = (
        statement.value
        if isinstance(statement, (ast.Assign, ast.AnnAssign))
        else None
    )
    if value is None:
        return None
    try:
        ast.literal_eval(value)
    except (ValueError, TypeError):
        return None
    return f"{name} = {ast.unparse(value)}"


def _module_name_rebound_after(
    tree: ast.Module,
    name: str,
    before_line: int,
) -> bool:
    return any(
        statement.lineno > before_line and _statement_binds(statement, name)
        for statement in tree.body
    )


def _statement_binds(statement: ast.stmt, name: str) -> bool:
    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        return any(
            (alias.asname or alias.name.split(".")[0]) == name
            for alias in statement.names
        )
    if isinstance(statement, ast.Assign):
        return any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        )
    if isinstance(statement, ast.AnnAssign):
        return isinstance(statement.target, ast.Name) and statement.target.id == name
    if isinstance(statement, ast.TypeAlias):
        return isinstance(statement.name, ast.Name) and statement.name.id == name
    return isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and (
        statement.name == name
    )
