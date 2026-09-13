"""Detect indirect project-owned Pydantic FieldInfo declarations."""

from __future__ import annotations

import ast
from collections.abc import Callable

from arclith_cli.entity_contract_ast import module_imports
from arclith_cli.import_origins import (
    absolute_import,
    project_module_tree,
    pydantic_field_info_references,
    pydantic_field_references,
)
from arclith_cli.project_paths import ProjectPaths


def validate_indirect_field_metadata(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    fields: tuple[ast.AnnAssign, ...],
    typing_kind: Callable[[ast.expr], str | None],
) -> None:
    """Reject project-owned references that evaluate to Pydantic FieldInfo."""
    pydantic_names, pydantic_modules = pydantic_field_references(paths, tree, module)
    names = set(pydantic_names)
    modules = set(pydantic_modules)
    for field in fields:
        assert isinstance(field.target, ast.Name)
        metadata = [
            expression
            for expression in annotation_metadata(field.annotation, typing_kind)
            if not _is_pydantic_field(expression, names, modules)
        ]
        unsafe_metadata = any(
            contains_project_field_info(
                paths,
                tree,
                module,
                expression,
                reject_unresolved_imports=True,
            )
            for expression in metadata
        )
        unsafe_default = (
            field.value is not None
            and not _is_pydantic_field(field.value, names, modules)
            and contains_project_field_info(paths, tree, module, field.value)
        )
        if unsafe_metadata or unsafe_default:
            raise ValueError(
                f"Indirect Pydantic Field metadata for {field.target.id!r} cannot "
                "be projected safely; inline Field(...) on the entity field"
            )


def contains_project_field_info(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    expression: ast.AST,
    visited: set[tuple[str, str]] | None = None,
    *,
    reject_unresolved_imports: bool = False,
) -> bool:
    """Follow project references and report whether they build FieldInfo."""
    pydantic_names, pydantic_modules = pydantic_field_references(
        paths,
        tree,
        module,
    )
    field_info_names, field_info_modules = pydantic_field_info_references(
        paths,
        tree,
        module,
    )
    if _contains_pydantic_metadata_constructor(
        expression,
        field_names=set(pydantic_names),
        field_modules=set(pydantic_modules),
        field_info_names=set(field_info_names),
        field_info_modules=set(field_info_modules),
    ):
        return True

    visited = set() if visited is None else visited
    for reference in _loaded_references(expression):
        target = _project_reference(paths, tree, module, reference)
        if target is None:
            if reject_unresolved_imports and _is_imported_reference(tree, reference):
                return True
            continue
        target_tree, target_module, target_name, target_node = target
        key = (target_module, target_name)
        if key in visited:
            continue
        visited.add(key)
        if contains_project_field_info(
            paths,
            target_tree,
            target_module,
            target_node,
            visited,
            reject_unresolved_imports=reject_unresolved_imports,
        ):
            return True
    return False


def annotation_metadata(
    annotation: ast.expr,
    typing_kind: Callable[[ast.expr], str | None],
) -> tuple[ast.expr, ...]:
    """Return only metadata expressions from nested Annotated declarations."""
    metadata: list[ast.expr] = []

    def visit(node: ast.expr) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                parsed = ast.parse(node.value, mode="eval").body
            except SyntaxError:
                return
            visit(parsed)
            return
        if not isinstance(node, ast.Subscript):
            return
        kind = typing_kind(node.value)
        if kind == "Literal":
            return
        arguments = _subscript_arguments(node.slice)
        if kind == "Annotated":
            if arguments:
                visit(arguments[0])
            metadata.extend(arguments[1:])
            return
        for argument in arguments:
            visit(argument)

    visit(annotation)
    return tuple(metadata)


def _project_reference(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    reference: str,
) -> tuple[ast.Module, str, str, ast.AST] | None:
    local = _local_declaration(tree, reference)
    if local is not None:
        return tree, module, reference, local
    root, separator, attributes = reference.partition(".")
    if separator:
        imported_root = _imported_symbol(paths, tree, module, root)
        if imported_root is not None:
            imported_tree, imported_module, imported_name = imported_root
            imported_reference = f"{imported_name}.{attributes}"
            declaration = _local_declaration(imported_tree, imported_reference)
            if declaration is not None:
                return (
                    imported_tree,
                    imported_module,
                    imported_reference,
                    declaration,
                )
    imported = (
        _qualified_imported_symbol(paths, tree, module, reference)
        if "." in reference
        else _imported_symbol(paths, tree, module, reference)
    )
    if imported is None:
        return None
    imported_tree, imported_module, imported_name = imported
    declaration = _local_declaration(imported_tree, imported_name)
    if declaration is None:
        return None
    return imported_tree, imported_module, imported_name, declaration


def _local_declaration(tree: ast.Module, reference: str) -> ast.AST | None:
    root, *attributes = reference.split(".")
    current = _named_declaration(tree.body, root)
    for attribute in attributes:
        if not isinstance(current, ast.ClassDef):
            return None
        current = _named_declaration(current.body, attribute)
    return current


def _named_declaration(statements: list[ast.stmt], name: str) -> ast.AST | None:
    for statement in statements:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if statement.name == name:
                return statement
        elif isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        ):
            return statement.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == name
        ):
            return statement.value
        elif (
            isinstance(statement, ast.TypeAlias)
            and isinstance(statement.name, ast.Name)
            and statement.name.id == name
        ):
            return statement.value
    return None


def _imported_symbol(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    name: str,
) -> tuple[ast.Module, str, str] | None:
    for statement in module_imports(tree):
        if not isinstance(statement, ast.ImportFrom):
            continue
        for alias in statement.names:
            if (alias.asname or alias.name) != name:
                continue
            imported_module = absolute_import(statement, module)
            if statement.module is None:
                imported_module = f"{imported_module}.{alias.name}"
            imported_tree = project_module_tree(paths, imported_module)
            if imported_tree is not None:
                return imported_tree, imported_module, alias.name
    return None


def _qualified_imported_symbol(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    name: str,
) -> tuple[ast.Module, str, str] | None:
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
                    imported_module = (
                        f"{absolute_import(statement, module)}.{alias.name}"
                    )
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


def _loaded_references(expression: ast.AST) -> set[str]:
    references: set[str] = set()

    class Collector(ast.NodeVisitor):
        def visit_Attribute(self, node: ast.Attribute) -> None:
            dotted = _dotted_name(node)
            if dotted is not None:
                references.add(dotted)
                return
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, ast.Load):
                references.add(node.id)

    Collector().visit(expression)
    return references


def _contains_pydantic_metadata_constructor(
    expression: ast.AST,
    *,
    field_names: set[str],
    field_modules: set[str],
    field_info_names: set[str],
    field_info_modules: set[str],
) -> bool:
    return any(
        isinstance(node, ast.expr)
        and (
            _is_pydantic_field(node, field_names, field_modules)
            or _is_pydantic_field_info(
                node,
                field_info_names,
                field_info_modules,
            )
        )
        for node in ast.walk(expression)
    )


def _is_pydantic_field(
    node: ast.expr | None,
    names: set[str],
    modules: set[str],
) -> bool:
    if not isinstance(node, ast.Call):
        return False
    function = node.func
    return (isinstance(function, ast.Name) and function.id in names) or (
        isinstance(function, ast.Attribute)
        and function.attr == "Field"
        and _root_name(function.value) in modules
    )


def _is_pydantic_field_info(
    node: ast.expr | None,
    names: set[str],
    modules: set[str],
) -> bool:
    if not isinstance(node, ast.Call):
        return False
    function = node.func
    return (isinstance(function, ast.Name) and function.id in names) or (
        isinstance(function, ast.Attribute)
        and function.attr == "FieldInfo"
        and _root_name(function.value) in modules
    )


def _is_imported_reference(tree: ast.Module, reference: str) -> bool:
    root = reference.split(".", maxsplit=1)[0]
    for statement in module_imports(tree):
        if isinstance(statement, ast.Import):
            if any(
                (alias.asname or alias.name.split(".")[0]) == root
                for alias in statement.names
            ):
                return True
        elif any((alias.asname or alias.name) == root for alias in statement.names):
            return True
    return False


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _dotted_name(node: ast.Attribute) -> str | None:
    parts = [node.attr]
    value = node.value
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if not isinstance(value, ast.Name):
        return None
    parts.append(value.id)
    return ".".join(reversed(parts))


def _subscript_arguments(node: ast.expr) -> tuple[ast.expr, ...]:
    if isinstance(node, ast.Tuple):
        return tuple(node.elts)
    return (node,)
