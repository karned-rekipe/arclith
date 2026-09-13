"""Inspect project-owned entity fields without importing application code."""

from __future__ import annotations

import ast
import builtins
from copy import deepcopy
from dataclasses import dataclass

from arclith_cli.entity_contract_ast import (
    field_dependencies,
    module_declarations,
    qualify_class_dependencies,
)
from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.import_origins import absolute_import, pydantic_field_references
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


def inspect_entity_contract(
    paths: ProjectPaths,
    entity: EntityInfo,
) -> EntityContract:
    """Return public, entity-owned Pydantic fields as static source snapshots."""
    if not entity.file_path.is_file():
        return EntityContract((), (), (), ())

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

    fields = tuple(_business_fields(models[0]))
    fields = qualify_class_dependencies(models[0], fields, entity.pascal)
    module = paths.import_path("domain", "models", entity.file_path.stem)
    pydantic_names, pydantic_modules = pydantic_field_references(paths, tree, module)
    names = set(pydantic_names)
    modules = set(pydantic_modules)
    fields = tuple(
        _sanitize_input_field(
            field,
            pydantic_names=names,
            pydantic_modules=modules,
        )
        for field in fields
    )
    imports = _field_imports(tree, fields, module)
    return EntityContract(
        imports=imports,
        create_fields=tuple(ast.unparse(field) for field in fields),
        update_fields=tuple(
            ast.unparse(
                _optional_update_field(
                    field,
                    pydantic_names=names,
                    pydantic_modules=modules,
                )
            )
            for field in fields
        ),
        field_names=tuple(
            field.target.id for field in fields if isinstance(field.target, ast.Name)
        ),
    )


def _business_fields(model: ast.ClassDef) -> list[ast.AnnAssign]:
    return [
        statement
        for statement in model.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and not statement.target.id.startswith("_")
        and statement.target.id != "model_config"
        and statement.target.id not in _ENTITY_MANAGED_FIELDS
        and not _is_class_var(statement.annotation)
    ]


def _is_class_var(annotation: ast.expr) -> bool:
    return any(
        (isinstance(node, ast.Name) and node.id == "ClassVar")
        or (isinstance(node, ast.Attribute) and node.attr == "ClassVar")
        for node in ast.walk(annotation)
    )


def _field_imports(
    tree: ast.Module,
    fields: tuple[ast.AnnAssign, ...],
    module: str,
) -> tuple[str, ...]:
    used = field_dependencies(fields)
    resolved = set(dir(builtins))
    imports: list[str] = []
    for statement in tree.body:
        if not isinstance(statement, (ast.Import, ast.ImportFrom)):
            continue
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
) -> ast.AnnAssign:
    result = _sanitize_input_field(
        field,
        pydantic_names=pydantic_names,
        pydantic_modules=pydantic_modules,
        partial_update=True,
    )
    if _is_pydantic_field(result.value, pydantic_names, pydantic_modules):
        assert isinstance(result.value, ast.Call)
        result.value.keywords.insert(
            0,
            ast.keyword(arg="default", value=ast.Constant(value=None)),
        )
    else:
        result.value = ast.Call(
            func=ast.Name(id="Field", ctx=ast.Load()),
            args=[],
            keywords=[ast.keyword(arg="default", value=ast.Constant(value=None))],
        )
    return ast.fix_missing_locations(result)


def _sanitize_input_field(
    field: ast.AnnAssign,
    *,
    pydantic_names: set[str],
    pydantic_modules: set[str],
    partial_update: bool = False,
) -> ast.AnnAssign:
    result = deepcopy(field)
    removed = {"exclude", "exclude_if"}
    if partial_update:
        removed.update({"default", "default_factory", "validate_default"})
    for node in ast.walk(result):
        if not isinstance(node, ast.expr):
            continue
        if not _is_pydantic_field(node, pydantic_names, pydantic_modules):
            continue
        assert isinstance(node, ast.Call)
        if partial_update:
            node.args = []
        node.keywords = [
            keyword for keyword in node.keywords if keyword.arg not in removed
        ]
    return ast.fix_missing_locations(result)


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
        and isinstance(function.value, ast.Name)
        and function.value.id in modules
    )
