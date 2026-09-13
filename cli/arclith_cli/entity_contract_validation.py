"""Validate statically projected entity input contracts."""

from __future__ import annotations

import ast

from arclith_cli.entity_contract_ast import module_imports
from arclith_cli.import_origins import (
    absolute_import,
    project_module_tree,
    pydantic_field_references,
)
from arclith_cli.project_paths import ProjectPaths


def validate_model_config(model: ast.ClassDef, entity_name: str) -> None:
    """Reject model configurations whose input aliases cannot be inspected."""
    for statement in model.body:
        value = _direct_model_config_value(statement)
        if value is None:
            finder = _ModelConfigReferenceFinder()
            finder.visit(statement)
            if finder.found:
                raise ValueError(
                    f"{entity_name}.model_config is defined or modified through "
                    "class control flow that cannot be projected safely; use one "
                    "direct static assignment"
                )
            continue
        alias_generator = _configuration_has_key(value, "alias_generator")
        if alias_generator is not False:
            reason = "contains" if alias_generator else "may contain"
            raise ValueError(
                f"{entity_name}.model_config {reason} an alias_generator that cannot "
                "be projected safely; inline a static config and declare explicit "
                "Field(alias=...) values on business fields"
            )


def _direct_model_config_value(statement: ast.stmt) -> ast.expr | None:
    if isinstance(statement, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "model_config"
        for target in statement.targets
    ):
        return statement.value
    if (
        isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and statement.target.id == "model_config"
    ):
        return statement.value
    return None


class _ModelConfigReferenceFinder(ast.NodeVisitor):
    def __init__(self) -> None:
        self.found = False

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "model_config":
            self.found = True

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return


def _configuration_has_key(value: ast.expr, key: str) -> bool | None:
    if isinstance(value, ast.Call):
        if any(keyword.arg is None for keyword in value.keywords):
            return None
        return any(keyword.arg == key for keyword in value.keywords)
    if isinstance(value, ast.Dict):
        if any(
            item is None
            or not isinstance(item, ast.Constant)
            or not isinstance(item.value, str)
            for item in value.keys
        ):
            return None
        return any(
            isinstance(item, ast.Constant) and item.value == key for item in value.keys
        )
    return None


def validate_input_aliases(
    fields: tuple[ast.AnnAssign, ...],
    pydantic_names: set[str],
    pydantic_modules: set[str],
) -> None:
    """Reject ambiguous aliases and aliases colliding with CRUD metadata."""
    reserved = {"uuid", "version"}
    for field in fields:
        assert isinstance(field.target, ast.Name)
        finders: list[_PydanticAliasCollisionFinder] = []
        for expression, parse_deferred_strings in (
            (field.annotation, True),
            (field.value, False),
        ):
            if expression is None:
                continue
            finder = _PydanticAliasCollisionFinder(
                reserved=reserved,
                pydantic_names=pydantic_names,
                pydantic_modules=pydantic_modules,
                parse_deferred_strings=parse_deferred_strings,
            )
            finder.visit(expression)
            finders.append(finder)
        collisions: set[str] = set().union(
            *(finder.collisions for finder in finders)
        )
        if collisions:
            raise ValueError(
                f"Input aliases for {field.target.id!r} collide with technical CRUD "
                f"fields: {', '.join(sorted(collisions))}"
            )
        if any(finder.has_unresolved_metadata for finder in finders):
            raise ValueError(
                f"Pydantic Field metadata for {field.target.id!r} cannot be resolved "
                "statically; inline Field options and use literal strings, AliasPath, "
                "or AliasChoices for aliases"
            )


class _PydanticAliasCollisionFinder(ast.NodeVisitor):
    def __init__(
        self,
        *,
        reserved: set[str],
        pydantic_names: set[str],
        pydantic_modules: set[str],
        parse_deferred_strings: bool,
    ) -> None:
        self._reserved = reserved
        self._pydantic_names = pydantic_names
        self._pydantic_modules = pydantic_modules
        self._parse_deferred_strings = parse_deferred_strings
        self.collisions: set[str] = set()
        self.has_unresolved_metadata = False

    def visit_Constant(self, node: ast.Constant) -> None:
        if not self._parse_deferred_strings or not isinstance(node.value, str):
            return
        try:
            expression = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return
        self.visit(expression)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        kind = reference_name(node.value)
        if kind == "Literal":
            return
        if kind == "Annotated":
            arguments = _subscript_arguments(node.slice)
            if arguments:
                self.visit(arguments[0])
            parse_deferred_strings = self._parse_deferred_strings
            self._parse_deferred_strings = False
            for metadata in arguments[1:]:
                self.visit(metadata)
            self._parse_deferred_strings = parse_deferred_strings
            return
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if not is_pydantic_field(
            node,
            self._pydantic_names,
            self._pydantic_modules,
        ):
            self.generic_visit(node)
            return
        if any(keyword.arg is None for keyword in node.keywords):
            self.has_unresolved_metadata = True
            return
        for keyword in node.keywords:
            if keyword.arg not in {"alias", "validation_alias"}:
                continue
            aliases = _static_input_aliases(keyword.arg, keyword.value)
            if aliases is None:
                self.has_unresolved_metadata = True
            else:
                self.collisions.update(aliases & self._reserved)


def validate_type_alias_metadata(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    fields: tuple[ast.AnnAssign, ...],
) -> None:
    """Reject project aliases whose Pydantic metadata cannot be sanitized safely."""
    visited: set[tuple[str, str]] = set()
    for field in fields:
        for name in _annotation_names(field.annotation):
            _validate_alias(paths, tree, module, name, visited)


def _validate_alias(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    name: str,
    visited: set[tuple[str, str]],
) -> None:
    reference = (module, name)
    if reference in visited:
        return
    visited.add(reference)
    value = _local_alias_value(tree, name)
    if value is None:
        imported = _imported_symbol(paths, tree, module, name)
        if imported is None:
            return
        imported_tree, imported_module, imported_name = imported
        _validate_alias(paths, imported_tree, imported_module, imported_name, visited)
        return

    pydantic_names, pydantic_modules = pydantic_field_references(
        paths,
        tree,
        module,
    )
    finder = _PydanticFieldFinder(
        pydantic_names=set(pydantic_names),
        pydantic_modules=set(pydantic_modules),
    )
    finder.visit(value)
    if finder.found:
        raise ValueError(
            f"Type alias {name!r} contains Pydantic Field metadata that cannot be "
            "projected safely; inline Annotated metadata on the entity field"
        )
    for dependency in _annotation_names(value):
        _validate_alias(paths, tree, module, dependency, visited)


def _local_alias_value(tree: ast.Module, name: str) -> ast.expr | None:
    for statement in tree.body:
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
            and reference_name(statement.annotation) == "TypeAlias"
        ):
            return statement.value
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == name
            and isinstance(statement.value, ast.Subscript)
            and reference_name(statement.value.value) == "Annotated"
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
            imported_tree = project_module_tree(paths, imported_module)
            if imported_tree is not None:
                return imported_tree, imported_module, alias.name
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


def _annotation_names(annotation: ast.expr) -> set[str]:
    names: set[str] = set()

    def visit(node: ast.AST, *, parse_string: bool) -> None:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            names.add(node.id)
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
            kind = reference_name(node.value)
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


def _static_input_aliases(kind: str, value: ast.expr) -> set[str] | None:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return {value.value}
    if kind == "alias" or not isinstance(value, ast.Call):
        return None
    reference = reference_name(value.func)
    if reference == "AliasPath":
        return _static_alias_path(value)
    if reference != "AliasChoices":
        return None
    aliases: set[str] = set()
    for choice in value.args:
        resolved = (
            _static_alias_path(choice)
            if isinstance(choice, ast.Call)
            and reference_name(choice.func) == "AliasPath"
            else _static_input_aliases("validation_alias", choice)
        )
        if resolved is None:
            return None
        aliases.update(resolved)
    return aliases


def _static_alias_path(value: ast.Call) -> set[str] | None:
    if not value.args:
        return None
    first = value.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return {first.value}
    return None


def is_pydantic_field(
    node: ast.expr | None,
    names: set[str],
    modules: set[str],
) -> bool:
    """Return whether an expression is a recognized Pydantic Field call."""
    if not isinstance(node, ast.Call):
        return False
    function = node.func
    return (isinstance(function, ast.Name) and function.id in names) or (
        isinstance(function, ast.Attribute)
        and function.attr == "Field"
        and root_name(function.value) in modules
    )


def root_name(node: ast.expr) -> str | None:
    """Return the root identifier from an attribute chain."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def reference_name(node: ast.expr) -> str | None:
    """Return the final identifier represented by an expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _subscript_arguments(node: ast.expr) -> tuple[ast.expr, ...]:
    if isinstance(node, ast.Tuple):
        return tuple(node.elts)
    return (node,)
