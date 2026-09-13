"""Inspect project-owned entity fields without importing application code."""

from __future__ import annotations

import ast
import builtins
from copy import deepcopy
from dataclasses import dataclass

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
    module = paths.import_path("domain", "models", entity.file_path.stem)
    imports = _field_imports(tree, fields, module)
    pydantic_names, pydantic_modules = pydantic_field_references(paths, tree, module)
    return EntityContract(
        imports=imports,
        create_fields=tuple(ast.unparse(field) for field in fields),
        update_fields=tuple(
            ast.unparse(
                _optional_update_field(
                    field,
                    pydantic_names=set(pydantic_names),
                    pydantic_modules=set(pydantic_modules),
                )
            )
            for field in fields
        ),
        field_names=tuple(field.target.id for field in fields),
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
    used = {
        node.id
        for field in fields
        for node in ast.walk(field)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
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
        declared = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        }
        declared.update(
            target.id
            for statement in tree.body
            if isinstance(statement, (ast.Assign, ast.AnnAssign))
            for target in (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            if isinstance(target, ast.Name)
        )
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
    result = deepcopy(field)
    if _is_pydantic_field(result.value, pydantic_names, pydantic_modules):
        assert isinstance(result.value, ast.Call)
        result.value.args = []
        result.value.keywords = [
            keyword
            for keyword in result.value.keywords
            if keyword.arg not in {"default", "default_factory"}
        ]
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
