"""Inspect project-owned entity fields without importing application code."""

from __future__ import annotations

import ast
import builtins
from copy import deepcopy
from dataclasses import dataclass

from arclith_cli.entity_contract_ast import (
    field_dependencies,
    module_imports,
    module_declarations,
    qualify_class_dependencies,
)
from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.entity_contract_validation import (
    TypingReferences,
    is_pydantic_field as _is_pydantic_field,
    typing_references,
    validate_input_aliases as _validate_input_aliases,
    validate_model_config as _validate_model_config,
    validate_type_alias_metadata as _validate_type_alias_metadata,
)
from arclith_cli.entity_field_metadata import validate_indirect_field_metadata
from arclith_cli.import_origins import (
    absolute_import,
    pydantic_field_info_references,
    pydantic_field_references,
)
from arclith_cli.project_paths import ProjectPaths

_ENTITY_MANAGED_FIELDS = (
    "uuid",
    "created_at",
    "created_by",
    "updated_at",
    "updated_by",
    "deleted_at",
    "deleted_by",
    "version",
)


@dataclass(frozen=True)
class EntityContract:
    """Declarative business fields that may be copied into CRUD inputs."""

    imports: tuple[str, ...]
    create_fields: tuple[str, ...]
    update_fields: tuple[str, ...]
    field_names: tuple[str, ...]
    update_field_names: tuple[str, ...]
    support_field_name: str


def inspect_entity_contract(
    paths: ProjectPaths,
    entity: EntityInfo,
) -> EntityContract:
    """Return public, entity-owned Pydantic fields as static source snapshots."""
    if not entity.file_path.is_file():
        return EntityContract((), (), (), (), (), "_ArclithCrudField")

    tree = ast.parse(
        entity.file_path.read_text(encoding="utf-8"),
        filename=str(entity.file_path),
    )
    models = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == entity.pascal
    ]
    if len(models) != 1:
        raise ValueError(
            f"Expected one entity model named {entity.pascal!r} in {entity.file_path}"
        )

    typing = typing_references(tree)
    fields = tuple(_business_fields(models[0], typing))
    fields = qualify_class_dependencies(
        models[0],
        fields,
        entity.pascal,
        typing.kind,
    )
    update_fields = tuple(
        field
        for field in fields
        if not _is_typing_marker(field.annotation, "Final", typing)
    )
    support_field_name = _available_support_name(
        "_ArclithCrudField",
        field_dependencies(fields, typing.kind),
    )
    module = paths.import_path("domain", "models", entity.file_path.stem)
    pydantic_names, pydantic_modules = pydantic_field_references(paths, tree, module)
    field_info_names, field_info_modules = pydantic_field_info_references(
        paths,
        tree,
        module,
    )
    names = set(pydantic_names)
    modules = set(pydantic_modules)
    _validate_model_config(models[0], entity.pascal)
    _validate_input_aliases(
        fields,
        names,
        modules,
        set(field_info_names),
        set(field_info_modules),
        typing,
    )
    validate_indirect_field_metadata(paths, tree, module, fields, typing.kind)
    _validate_type_alias_metadata(paths, tree, module, fields)
    fields = tuple(
        _sanitize_input_field(
            field,
            pydantic_names=names,
            pydantic_modules=modules,
            defer_default_factory=True,
            typing=typing,
            support_field_name=support_field_name,
        )
        for field in fields
    )
    imports = _field_imports(tree, fields, module, typing)
    return EntityContract(
        imports=imports,
        create_fields=tuple(ast.unparse(field) for field in fields),
        update_fields=tuple(
            ast.unparse(
                _optional_update_field(
                    field,
                    pydantic_names=names,
                    pydantic_modules=modules,
                    typing=typing,
                    support_field_name=support_field_name,
                )
            )
            for field in update_fields
        ),
        field_names=tuple(
            field.target.id for field in fields if isinstance(field.target, ast.Name)
        ),
        update_field_names=tuple(
            field.target.id
            for field in update_fields
            if isinstance(field.target, ast.Name)
        ),
        support_field_name=support_field_name,
    )


def _business_fields(
    model: ast.ClassDef,
    typing: TypingReferences,
) -> list[ast.AnnAssign]:
    return [
        statement
        for statement in model.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and not statement.target.id.startswith("_")
        and statement.target.id != "model_config"
        and statement.target.id not in _ENTITY_MANAGED_FIELDS
        and not _is_typing_marker(statement.annotation, "ClassVar", typing)
        and not (
            statement.value is not None
            and _is_typing_marker(statement.annotation, "Final", typing)
        )
    ]


def _is_typing_marker(
    annotation: ast.expr,
    marker: str,
    typing: TypingReferences,
) -> bool:
    def visit(node: ast.AST) -> bool:
        if isinstance(node, ast.expr) and typing.kind(node) == marker:
            return True
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                expression = ast.parse(node.value, mode="eval").body
            except SyntaxError:
                return False
            return visit(expression)
        if isinstance(node, ast.Subscript):
            kind = typing.kind(node.value)
            if kind == "Literal":
                return False
            if kind == "Annotated":
                arguments = (
                    tuple(node.slice.elts)
                    if isinstance(node.slice, ast.Tuple)
                    else (node.slice,)
                )
                return bool(arguments) and visit(arguments[0])
        return any(visit(child) for child in ast.iter_child_nodes(node))

    return visit(annotation)


def _available_support_name(preferred: str, unavailable: set[str]) -> str:
    candidate = preferred
    while candidate in unavailable:
        candidate += "_"
    return candidate


def _field_imports(
    tree: ast.Module,
    fields: tuple[ast.AnnAssign, ...],
    module: str,
    typing: TypingReferences,
) -> tuple[str, ...]:
    used = field_dependencies(fields, typing.kind)
    resolved = set(dir(builtins))
    imports: list[str] = []
    for statement in module_imports(tree):
        local_names = {
            alias.asname or alias.name.split(".")[0]: alias for alias in statement.names
        }
        selected = sorted(used & local_names.keys())
        if not selected:
            continue
        aliases = [local_names[name] for name in selected]
        if isinstance(statement, ast.ImportFrom):
            rendered: ast.Import | ast.ImportFrom = ast.ImportFrom(
                module=absolute_import(statement, module),
                names=aliases,
                level=0,
            )
        else:
            rendered = ast.Import(names=aliases)
        imports.append(ast.unparse(rendered))
        resolved.update(selected)

    unresolved = used - resolved
    if unresolved:
        declared = module_declarations(tree)
        local = sorted(unresolved & declared)
        if local:
            imports.append(f"from {module} import {', '.join(local)}")
            resolved.update(local)

    unresolved = used - resolved
    if unresolved:
        raise ValueError(
            "Unresolved entity field dependencies cannot be projected into CRUD "
            "commands: " + ", ".join(sorted(unresolved))
        )
    return tuple(imports)


def _optional_update_field(
    field: ast.AnnAssign,
    *,
    pydantic_names: set[str],
    pydantic_modules: set[str],
    typing: TypingReferences,
    support_field_name: str,
) -> ast.AnnAssign:
    result = _sanitize_input_field(
        field,
        pydantic_names=pydantic_names,
        pydantic_modules=pydantic_modules,
        partial_update=True,
        typing=typing,
        support_field_name=support_field_name,
    )
    _make_omissible(
        result,
        pydantic_names,
        pydantic_modules,
        support_field_name=support_field_name,
    )
    return ast.fix_missing_locations(result)


def _make_omissible(
    field: ast.AnnAssign,
    pydantic_names: set[str],
    pydantic_modules: set[str],
    *,
    constructor: ast.expr | None = None,
    support_field_name: str,
) -> None:
    """Allow omission without widening the field's accepted input type."""
    if _is_pydantic_field(field.value, pydantic_names, pydantic_modules):
        assert isinstance(field.value, ast.Call)
        field.value.keywords.insert(
            0,
            ast.keyword(arg="default", value=ast.Constant(value=None)),
        )
    else:
        field.value = ast.Call(
            func=constructor or ast.Name(id=support_field_name, ctx=ast.Load()),
            args=[],
            keywords=[ast.keyword(arg="default", value=ast.Constant(value=None))],
        )


def _sanitize_input_field(
    field: ast.AnnAssign,
    *,
    pydantic_names: set[str],
    pydantic_modules: set[str],
    partial_update: bool = False,
    defer_default_factory: bool = False,
    typing: TypingReferences,
    support_field_name: str,
) -> ast.AnnAssign:
    factory_constructor = (
        _pydantic_keyword_constructor(
            field,
            keyword="default_factory",
            pydantic_names=pydantic_names,
            pydantic_modules=pydantic_modules,
            typing=typing,
        )
        if defer_default_factory
        else None
    )
    deferred_factory = factory_constructor is not None
    result = deepcopy(field)
    removed = {"exclude", "exclude_if", "serialization_alias"}
    if partial_update:
        removed.update({"default", "default_factory", "validate_default"})
    elif deferred_factory:
        removed.update({"default_factory", "validate_default"})
    result.annotation = _QuotedAnnotationSanitizer(
        pydantic_names=pydantic_names,
        pydantic_modules=pydantic_modules,
        removed=removed,
        clear_default=partial_update,
        typing=typing,
    ).visit(result.annotation)
    _sanitize_pydantic_field_calls(
        result,
        pydantic_names=pydantic_names,
        pydantic_modules=pydantic_modules,
        removed=removed,
        clear_default=partial_update,
    )
    if deferred_factory:
        _make_omissible(
            result,
            pydantic_names,
            pydantic_modules,
            constructor=factory_constructor,
            support_field_name=support_field_name,
        )
    return ast.fix_missing_locations(result)


def _pydantic_keyword_constructor(
    field: ast.AnnAssign,
    *,
    keyword: str,
    pydantic_names: set[str],
    pydantic_modules: set[str],
    typing: TypingReferences,
) -> ast.expr | None:
    annotation_finder = _PydanticKeywordFinder(
        keyword=keyword,
        pydantic_names=pydantic_names,
        pydantic_modules=pydantic_modules,
        parse_deferred_strings=True,
        typing=typing,
    )
    annotation_finder.visit(field.annotation)
    if annotation_finder.constructor is not None or field.value is None:
        return annotation_finder.constructor
    value_finder = _PydanticKeywordFinder(
        keyword=keyword,
        pydantic_names=pydantic_names,
        pydantic_modules=pydantic_modules,
        parse_deferred_strings=False,
        typing=typing,
    )
    value_finder.visit(field.value)
    return value_finder.constructor


def _sanitize_pydantic_field_calls(
    tree: ast.AST,
    *,
    pydantic_names: set[str],
    pydantic_modules: set[str],
    removed: set[str],
    clear_default: bool,
) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.expr):
            continue
        if not _is_pydantic_field(node, pydantic_names, pydantic_modules):
            continue
        assert isinstance(node, ast.Call)
        if clear_default:
            node.args = []
        node.keywords = [
            keyword for keyword in node.keywords if keyword.arg not in removed
        ]


class _QuotedAnnotationSanitizer(ast.NodeTransformer):
    def __init__(
        self,
        *,
        pydantic_names: set[str],
        pydantic_modules: set[str],
        removed: set[str],
        clear_default: bool,
        typing: TypingReferences,
    ) -> None:
        self._pydantic_names = pydantic_names
        self._pydantic_modules = pydantic_modules
        self._removed = removed
        self._clear_default = clear_default
        self._typing = typing

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        if not isinstance(node.value, str):
            return node
        try:
            expression = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return node
        expression = self.visit(expression)
        _sanitize_pydantic_field_calls(
            expression,
            pydantic_names=self._pydantic_names,
            pydantic_modules=self._pydantic_modules,
            removed=self._removed,
            clear_default=self._clear_default,
        )
        result = deepcopy(node)
        result.value = ast.unparse(expression)
        return ast.copy_location(result, node)

    def visit_Subscript(self, node: ast.Subscript) -> ast.Subscript:
        kind = self._typing.kind(node.value)
        if kind == "Literal":
            return node
        if kind == "Annotated":
            if isinstance(node.slice, ast.Tuple):
                if node.slice.elts:
                    node.slice.elts[0] = self.visit(node.slice.elts[0])
            else:
                node.slice = self.visit(node.slice)
            return node
        node.slice = self.visit(node.slice)
        return node

    def visit_Call(self, node: ast.Call) -> ast.Call:
        return node


class _PydanticKeywordFinder(ast.NodeVisitor):
    def __init__(
        self,
        *,
        keyword: str,
        pydantic_names: set[str],
        pydantic_modules: set[str],
        parse_deferred_strings: bool,
        typing: TypingReferences,
    ) -> None:
        self._keyword = keyword
        self._pydantic_names = pydantic_names
        self._pydantic_modules = pydantic_modules
        self._parse_deferred_strings = parse_deferred_strings
        self._typing = typing
        self.constructor: ast.expr | None = None

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
            arguments = (
                tuple(node.slice.elts)
                if isinstance(node.slice, ast.Tuple)
                else (node.slice,)
            )
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
        if _is_pydantic_field(
            node,
            self._pydantic_names,
            self._pydantic_modules,
        ):
            if any(item.arg == self._keyword for item in node.keywords):
                self.constructor = deepcopy(node.func)
            return
        self.generic_visit(node)
