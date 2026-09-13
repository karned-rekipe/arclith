"""Validate statically projected entity input contracts."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from arclith_cli.entity_contract_ast import module_imports
from arclith_cli.entity_field_metadata import (
    annotation_metadata,
    contains_project_field_info,
)
from arclith_cli.entity_input_aliases import static_input_aliases
from arclith_cli.import_origins import (
    project_imported_symbol,
    project_qualified_imported_symbol,
    pydantic_field_references,
    uninspectable_external_reference,
)
from arclith_cli.project_paths import ProjectPaths


@dataclass(frozen=True)
class TypingReferences:
    """Local spellings of typing markers used while walking annotations."""

    names: dict[str, frozenset[str]]
    modules: frozenset[str]

    def kind(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return next(
                (kind for kind, names in self.names.items() if node.id in names),
                None,
            )
        if isinstance(node, ast.Attribute) and root_name(node.value) in self.modules:
            return node.attr if node.attr in self.names else None
        return None


def typing_references(tree: ast.Module) -> TypingReferences:
    """Resolve aliases for annotation markers imported from typing modules."""
    markers = ("Annotated", "ClassVar", "Final", "Literal", "TypeAlias")
    names: dict[str, set[str]] = {marker: {marker} for marker in markers}
    modules = {"typing", "typing_extensions"}
    for statement in module_imports(tree):
        if isinstance(statement, ast.ImportFrom) and statement.module in modules:
            for alias in statement.names:
                if alias.name in names:
                    names[alias.name].add(alias.asname or alias.name)
        elif isinstance(statement, ast.Import):
            modules.update(
                alias.asname or alias.name.split(".")[0]
                for alias in statement.names
                if alias.name in {"typing", "typing_extensions"}
            )
    return TypingReferences(
        names={kind: frozenset(values) for kind, values in names.items()},
        modules=frozenset(modules),
    )


def validate_model_config(model: ast.ClassDef, entity_name: str) -> None:
    """Reject model configurations whose input aliases cannot be inspected."""
    class_alias_generator = _keywords_have_key(model.keywords, "alias_generator")
    if class_alias_generator is not False:
        _raise_alias_generator_error(entity_name, class_alias_generator, "class")
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
            _raise_alias_generator_error(entity_name, alias_generator, "model_config")


def _raise_alias_generator_error(
    entity_name: str,
    present: bool | None,
    source: str,
) -> None:
    reason = "contains" if present else "may contain"
    raise ValueError(
        f"{entity_name} {source} {reason} an alias_generator that cannot be "
        "projected safely; inline a static config and declare explicit "
        "Field(alias=...) values on business fields"
    )


def _keywords_have_key(keywords: list[ast.keyword], key: str) -> bool | None:
    if any(keyword.arg == key for keyword in keywords):
        return True
    if any(keyword.arg is None for keyword in keywords):
        return None
    return False


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
    field_info_names: set[str],
    field_info_modules: set[str],
    alias_path_names: set[str],
    alias_path_modules: set[str],
    alias_choices_names: set[str],
    alias_choices_modules: set[str],
    typing: TypingReferences,
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
                field_info_names=field_info_names,
                field_info_modules=field_info_modules,
                alias_path_names=alias_path_names,
                alias_path_modules=alias_path_modules,
                alias_choices_names=alias_choices_names,
                alias_choices_modules=alias_choices_modules,
                parse_deferred_strings=parse_deferred_strings,
                typing=typing,
            )
            finder.visit(expression)
            finders.append(finder)
        collisions: set[str] = set().union(*(finder.collisions for finder in finders))
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
        field_info_names: set[str],
        field_info_modules: set[str],
        alias_path_names: set[str],
        alias_path_modules: set[str],
        alias_choices_names: set[str],
        alias_choices_modules: set[str],
        parse_deferred_strings: bool,
        typing: TypingReferences,
    ) -> None:
        self._reserved = reserved
        self._pydantic_names = pydantic_names
        self._pydantic_modules = pydantic_modules
        self._field_info_names = field_info_names
        self._field_info_modules = field_info_modules
        self._alias_path_names = alias_path_names
        self._alias_path_modules = alias_path_modules
        self._alias_choices_names = alias_choices_names
        self._alias_choices_modules = alias_choices_modules
        self._parse_deferred_strings = parse_deferred_strings
        self._typing = typing
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
        kind = self._typing.kind(node.value)
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
        if is_pydantic_field_info(
            node,
            self._field_info_names,
            self._field_info_modules,
        ):
            self.has_unresolved_metadata = True
            return
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
            aliases = static_input_aliases(
                keyword.arg,
                keyword.value,
                alias_path_names=self._alias_path_names,
                alias_path_modules=self._alias_path_modules,
                alias_choices_names=self._alias_choices_names,
                alias_choices_modules=self._alias_choices_modules,
            )
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
    typing = typing_references(tree)
    for field in fields:
        for name in _annotation_names(field.annotation, typing):
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
    if "." in name:
        imported = project_qualified_imported_symbol(paths, tree, module, name)
        if imported is None:
            _reject_uninspectable_alias(paths, tree, module, name)
            return
        imported_tree, imported_module, imported_name = imported
        _validate_alias(paths, imported_tree, imported_module, imported_name, visited)
        return
    typing = typing_references(tree)
    value = _local_alias_value(tree, name, typing)
    if value is None:
        imported = project_imported_symbol(paths, tree, module, name)
        if imported is None:
            _reject_uninspectable_alias(paths, tree, module, name)
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
        _validate_alias(paths, tree, module, dependency, visited)


def _reject_uninspectable_alias(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    name: str,
) -> None:
    if uninspectable_external_reference(paths, tree, module, name):
        raise ValueError(
            f"Imported annotation {name!r} cannot be inspected for Pydantic "
            "metadata; inline the external type alias before projection"
        )


def _local_alias_value(
    tree: ast.Module,
    name: str,
    typing: TypingReferences,
) -> ast.expr | None:
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


def is_pydantic_field_info(
    node: ast.expr | None,
    names: set[str],
    modules: set[str],
) -> bool:
    """Return whether an expression constructs Pydantic FieldInfo directly."""
    if not isinstance(node, ast.Call):
        return False
    function = node.func
    return (isinstance(function, ast.Name) and function.id in names) or (
        isinstance(function, ast.Attribute)
        and function.attr == "FieldInfo"
        and root_name(function.value) in modules
    )


def root_name(node: ast.expr) -> str | None:
    """Return the root identifier from an attribute chain."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _subscript_arguments(node: ast.expr) -> tuple[ast.expr, ...]:
    if isinstance(node, ast.Tuple):
        return tuple(node.elts)
    return (node,)
