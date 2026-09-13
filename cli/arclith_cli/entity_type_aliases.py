"""Validate type aliases referenced by projected entity annotations."""

from __future__ import annotations

import ast

from arclith_cli.entity_contract_validation import (
    TypingReferences,
    is_pydantic_field,
    typing_references,
)
from arclith_cli.entity_field_metadata import (
    annotation_metadata,
    contains_project_field_info,
)
from arclith_cli.import_origins import (
    project_imported_symbol,
    project_qualified_imported_symbol,
    pydantic_field_references,
    uninspectable_external_reference,
)
from arclith_cli.project_paths import ProjectPaths


def validate_type_alias_metadata(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    fields: tuple[ast.AnnAssign, ...],
) -> None:
    """Reject project aliases whose Pydantic metadata cannot be sanitized safely."""
    if not fields:
        return
    before_line = min(field.lineno for field in fields)
    visited: set[tuple[str, str]] = set()
    typing = typing_references(tree, before_line=before_line)
    for field in fields:
        for name in _annotation_names(field.annotation, typing):
            _validate_alias(
                paths,
                tree,
                module,
                name,
                visited,
                before_line=before_line,
            )


def _validate_alias(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    name: str,
    visited: set[tuple[str, str]],
    *,
    before_line: int | None,
) -> None:
    reference = (module, name)
    if reference in visited:
        return
    visited.add(reference)
    if "." in name:
        imported = project_qualified_imported_symbol(
            paths,
            tree,
            module,
            name,
            before_line=before_line,
        )
        if imported is None:
            _reject_uninspectable_alias(
                paths,
                tree,
                module,
                name,
                before_line=before_line,
            )
            return
        imported_tree, imported_module, imported_name = imported
        _validate_alias(
            paths,
            imported_tree,
            imported_module,
            imported_name,
            visited,
            before_line=None,
        )
        return
    typing = typing_references(tree, before_line=before_line)
    value = _local_alias_value(
        tree,
        name,
        typing,
        before_line=before_line,
    )
    if value is None:
        imported = project_imported_symbol(
            paths,
            tree,
            module,
            name,
            before_line=before_line,
        )
        if imported is None:
            _reject_uninspectable_alias(
                paths,
                tree,
                module,
                name,
                before_line=before_line,
            )
            return
        imported_tree, imported_module, imported_name = imported
        _validate_alias(
            paths,
            imported_tree,
            imported_module,
            imported_name,
            visited,
            before_line=None,
        )
        return

    pydantic_names, pydantic_modules = pydantic_field_references(
        paths,
        tree,
        module,
        before_line=before_line,
    )
    finder = _PydanticFieldFinder(
        pydantic_names=set(pydantic_names),
        pydantic_modules=set(pydantic_modules),
    )
    finder.visit(value)
    if finder.found or any(
        contains_project_field_info(
            paths,
            tree,
            module,
            metadata,
            reject_unresolved_imports=True,
        )
        for metadata in annotation_metadata(value, typing.kind)
    ):
        raise ValueError(
            f"Type alias {name!r} contains Pydantic Field metadata that cannot be "
            "projected safely; inline Annotated metadata on the entity field"
        )
    for dependency in _annotation_names(value, typing):
        _validate_alias(
            paths,
            tree,
            module,
            dependency,
            visited,
            before_line=before_line,
        )


def _reject_uninspectable_alias(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    name: str,
    *,
    before_line: int | None,
) -> None:
    if uninspectable_external_reference(
        paths,
        tree,
        module,
        name,
        before_line=before_line,
    ):
        raise ValueError(
            f"Imported annotation {name!r} cannot be inspected for Pydantic "
            "metadata; inline the external type alias before projection"
        )


def _local_alias_value(
    tree: ast.Module,
    name: str,
    typing: TypingReferences,
    *,
    before_line: int | None,
) -> ast.expr | None:
    statements = (
        statement
        for statement in reversed(tree.body)
        if before_line is None or statement.lineno <= before_line
    )
    for statement in statements:
        if isinstance(statement, ast.ImportFrom) and any(
            (alias.asname or alias.name) == name for alias in statement.names
        ):
            return None
        if isinstance(statement, ast.Import) and any(
            (alias.asname or alias.name.split(".")[0]) == name
            for alias in statement.names
        ):
            return None
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if statement.name == name:
                return None
        if (
            isinstance(statement, ast.TypeAlias)
            and isinstance(statement.name, ast.Name)
            and statement.name.id == name
        ):
            return statement.value
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == name
            and typing.kind(statement.annotation) == "TypeAlias"
        ):
            return statement.value
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == name
        ):
            return statement.value
    return None


class _PydanticFieldFinder(ast.NodeVisitor):
    def __init__(
        self,
        *,
        pydantic_names: set[str],
        pydantic_modules: set[str],
    ) -> None:
        self._pydantic_names = pydantic_names
        self._pydantic_modules = pydantic_modules
        self.found = False

    def visit_Call(self, node: ast.Call) -> None:
        if is_pydantic_field(node, self._pydantic_names, self._pydantic_modules):
            self.found = True
            return
        self.generic_visit(node)


def _annotation_names(
    annotation: ast.expr,
    typing: TypingReferences,
) -> set[str]:
    names: set[str] = set()

    def visit(node: ast.AST, *, parse_string: bool) -> None:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            names.add(node.id)
            return
        if isinstance(node, ast.Attribute):
            dotted = _dotted_name(node)
            if dotted is not None:
                names.add(dotted)
                return
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if not parse_string:
                return
            try:
                expression = ast.parse(node.value, mode="eval").body
            except SyntaxError:
                return
            visit(expression, parse_string=True)
            return
        if isinstance(node, ast.Subscript):
            kind = typing.kind(node.value)
            if kind == "Literal":
                return
            if kind == "Annotated":
                arguments = _subscript_arguments(node.slice)
                if arguments:
                    visit(arguments[0], parse_string=True)
                for metadata in arguments[1:]:
                    visit(metadata, parse_string=False)
                return
        for child in ast.iter_child_nodes(node):
            visit(child, parse_string=parse_string)

    visit(annotation, parse_string=True)
    return names


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
