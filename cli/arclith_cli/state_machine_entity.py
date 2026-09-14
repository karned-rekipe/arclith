"""Render and validate the entity-facing state-machine contract."""

from __future__ import annotations

import ast
from pathlib import Path

from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.state_machine_rendering import (
    render_state_documentation,
    render_state_errors,
    render_state_machine_entity,
    render_state_model,
    state_machine_state_module,
)
from arclith_cli.state_machine_spec import StateMachineSpec

__all__ = [
    "render_state_documentation",
    "render_state_errors",
    "render_state_machine_entity",
    "render_state_model",
    "state_machine_state_module",
]


# Bump whenever ``validate_existing_state_field`` accepts or rejects new forms.
STATE_MACHINE_EXISTING_ENTITY_VALIDATION_VERSION = 2


def validate_existing_state_field(
    entity: EntityInfo,
    spec: StateMachineSpec,
) -> None:
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
            f"Expected one top-level Entity declaration named {entity.pascal}"
        )
    fields = [
        statement
        for statement in models[0].body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and statement.target.id == spec.state_field
    ]
    if not fields:
        raise ValueError(
            f"Entity {entity.pascal} must declare typed field {spec.state_field!r}; "
            "add it explicitly, then replay the command"
        )
    if len(fields) != 1 or not _compatible_state_annotation(
        fields[0].annotation,
        spec,
        tree=tree,
        entity_file=entity.file_path,
    ):
        raise ValueError(
            f"Entity field {entity.pascal}.{spec.state_field} must be typed as "
            "a statically inspectable string-valued Enum/StrEnum or Literal "
            "containing exactly the declared states"
        )
    if not _state_assignment_is_protected(models[0], fields[0], tree=tree):
        raise ValueError(
            f"Entity field {entity.pascal}.{spec.state_field} must reject assignment; "
            "use ConfigDict(validate_assignment=True) with Field(..., frozen=True)"
        )
    if not _state_copy_is_controlled(models[0], spec.state_field):
        raise ValueError(
            f"Entity field {entity.pascal}.{spec.state_field} must reject generic "
            f"model_copy updates and expose a private _copy_with_{spec.state_field} "
            "method for the lifecycle"
        )


def _compatible_state_annotation(
    annotation: ast.expr,
    spec: StateMachineSpec,
    *,
    tree: ast.Module,
    entity_file: Path,
) -> bool:
    literal_states = _resolve_literal_values(
        annotation,
        tree=tree,
        entity_file=entity_file,
    )
    if literal_states is not None:
        return literal_states == set(spec.states)
    return _resolve_enum_values(
        annotation,
        tree=tree,
        entity_file=entity_file,
    ) == set(spec.states)


def _resolve_literal_values(
    annotation: ast.expr,
    *,
    tree: ast.Module,
    entity_file: Path,
    visited: frozenset[tuple[Path, str]] = frozenset(),
) -> set[str] | None:
    if isinstance(annotation, ast.Subscript):
        if not _is_imported_symbol(
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
    bindings = [
        statement
        for statement in tree.body
        if annotation.id in _bound_names(statement)
    ]
    if len(bindings) != 1:
        return None
    binding = bindings[0]
    alias_value = _alias_value(binding, annotation.id)
    if alias_value is not None:
        return _resolve_literal_values(
            alias_value,
            tree=tree,
            entity_file=entity_file,
            visited=visited | {key},
        )
    if not isinstance(binding, ast.ImportFrom):
        return None
    imported = next(
        (
            item
            for item in binding.names
            if (item.asname or item.name) == annotation.id
        ),
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
    return _resolve_literal_values(
        ast.Name(id=imported.name),
        tree=imported_tree,
        entity_file=module_file,
        visited=visited | {key},
    )


def _resolve_enum_values(
    annotation: ast.expr,
    *,
    tree: ast.Module,
    entity_file: Path,
    visited: frozenset[tuple[Path, str]] = frozenset(),
) -> set[str] | None:
    if not isinstance(annotation, ast.Name):
        return None
    symbol = annotation.id
    key = (entity_file, symbol)
    if key in visited:
        return None
    bindings = [statement for statement in tree.body if symbol in _bound_names(statement)]
    if len(bindings) != 1:
        return None
    binding = bindings[0]
    if isinstance(binding, ast.ClassDef):
        return _enum_values(binding, tree)
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
    return _resolve_enum_values(
        ast.Name(id=imported.name),
        tree=imported_tree,
        entity_file=module_file,
        visited=visited | {key},
    )


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


def _enum_values(declaration: ast.ClassDef, tree: ast.Module) -> set[str] | None:
    if not any(
        _is_imported_symbol(
            base,
            symbols=frozenset({"Enum", "StrEnum"}),
            modules=frozenset({"enum"}),
            tree=tree,
        )
        for base in declaration.bases
    ):
        return None
    values: list[str] = []
    for statement in declaration.body:
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
            continue
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            return None
        values.append(value.value)
    return set(values) if values else None


def _bound_names(statement: ast.stmt) -> set[str]:
    if isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return {statement.name}
    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        return {
            item.asname or item.name.split(".", 1)[0]
            for item in statement.names
        }
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


def _is_imported_symbol(
    expression: ast.expr,
    *,
    symbols: frozenset[str],
    modules: frozenset[str],
    tree: ast.Module,
) -> bool:
    if isinstance(expression, ast.Name):
        bindings = [
            statement
            for statement in tree.body
            if expression.id in _bound_names(statement)
        ]
        if len(bindings) != 1 or not isinstance(bindings[0], ast.ImportFrom):
            return False
        statement = bindings[0]
        return (
            statement.level == 0
            and statement.module in modules
            and any(
                item.name in symbols
                and (item.asname or item.name) == expression.id
                for item in statement.names
            )
        )
    if not (
        isinstance(expression, ast.Attribute)
        and expression.attr in symbols
        and isinstance(expression.value, ast.Name)
    ):
        return False
    module_alias = expression.value.id
    bindings = [
        statement for statement in tree.body if module_alias in _bound_names(statement)
    ]
    if len(bindings) != 1 or not isinstance(bindings[0], ast.Import):
        return False
    return any(
        item.name in modules and (item.asname or item.name) == module_alias
        for item in bindings[0].names
    )


def _state_assignment_is_protected(
    model: ast.ClassDef,
    field: ast.AnnAssign,
    *,
    tree: ast.Module,
) -> bool:
    config_options: dict[str, bool] = {}
    for statement in model.body:
        if not isinstance(statement, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == "model_config"
            for target in statement.targets
        ):
            continue
        if isinstance(statement.value, ast.Call) and _is_pydantic_callable(
            statement.value.func,
            "ConfigDict",
            tree,
        ):
            config_options.update(
                {
                    option.arg: option.value.value
                    for option in statement.value.keywords
                    if option.arg is not None
                    and isinstance(option.value, ast.Constant)
                    and isinstance(option.value.value, bool)
                }
            )
    if config_options.get("frozen") is True:
        return True
    if config_options.get("validate_assignment") is not True:
        return False
    value = field.value
    if not isinstance(value, ast.Call) or not _is_pydantic_callable(
        value.func,
        "Field",
        tree,
    ):
        return False
    return any(
        option.arg == "frozen"
        and isinstance(option.value, ast.Constant)
        and option.value.value is True
        for option in value.keywords
    )


def _is_pydantic_callable(
    expression: ast.expr,
    symbol: str,
    tree: ast.Module,
) -> bool:
    if isinstance(expression, ast.Name):
        return any(
            isinstance(statement, ast.ImportFrom)
            and statement.level == 0
            and statement.module == "pydantic"
            and any(
                imported.name == symbol
                and (imported.asname or imported.name) == expression.id
                for imported in statement.names
            )
            for statement in tree.body
        )
    if not (
        isinstance(expression, ast.Attribute)
        and expression.attr == symbol
        and isinstance(expression.value, ast.Name)
    ):
        return False
    module_alias = expression.value.id
    return any(
        isinstance(statement, ast.Import)
        and any(
            imported.name == "pydantic"
            and (imported.asname or imported.name) == module_alias
            for imported in statement.names
        )
        for statement in tree.body
    )


def _state_copy_is_controlled(model: ast.ClassDef, state_field: str) -> bool:
    methods = {
        statement.name: statement
        for statement in model.body
        if isinstance(statement, ast.FunctionDef)
    }
    public_copy = methods.get("model_copy")
    lifecycle_copy = methods.get(f"_copy_with_{state_field}")
    if public_copy is None or lifecycle_copy is None:
        return False
    public_body = _method_body(public_copy)
    lifecycle_body = _method_body(lifecycle_copy)
    return (
        len(public_body) == 2
        and _is_state_update_guard(public_body[0], state_field)
        and _is_public_model_copy_return(public_body[1])
        and len(lifecycle_body) == 1
        and _is_lifecycle_model_copy_return(lifecycle_body[0], state_field)
    )


def _method_body(
    method: ast.FunctionDef,
) -> list[ast.stmt]:
    body = list(method.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _is_state_update_guard(statement: ast.stmt, state_field: str) -> bool:
    if (
        not isinstance(statement, ast.If)
        or statement.orelse
        or len(statement.body) != 1
        or not isinstance(statement.body[0], ast.Raise)
        or not isinstance(statement.test, ast.BoolOp)
        or not isinstance(statement.test.op, ast.And)
        or len(statement.test.values) != 2
    ):
        return False
    return any(_is_update_not_none(value) for value in statement.test.values) and any(
        _is_state_in_update(value, state_field) for value in statement.test.values
    )


def _is_update_not_none(expression: ast.expr) -> bool:
    return (
        isinstance(expression, ast.Compare)
        and isinstance(expression.left, ast.Name)
        and expression.left.id == "update"
        and len(expression.ops) == 1
        and isinstance(expression.ops[0], ast.IsNot)
        and len(expression.comparators) == 1
        and isinstance(expression.comparators[0], ast.Constant)
        and expression.comparators[0].value is None
    )


def _is_state_in_update(expression: ast.expr, state_field: str) -> bool:
    return (
        isinstance(expression, ast.Compare)
        and isinstance(expression.left, ast.Constant)
        and expression.left.value == state_field
        and len(expression.ops) == 1
        and isinstance(expression.ops[0], ast.In)
        and len(expression.comparators) == 1
        and isinstance(expression.comparators[0], ast.Name)
        and expression.comparators[0].id == "update"
    )


def _is_public_model_copy_return(statement: ast.stmt) -> bool:
    if not isinstance(statement, ast.Return) or not isinstance(statement.value, ast.Call):
        return False
    call = statement.value
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    update = keywords.get("update")
    deep = keywords.get("deep")
    return (
        _is_super_model_copy(call)
        and not call.args
        and len(keywords) == 2
        and isinstance(update, ast.Name)
        and update.id == "update"
        and isinstance(deep, ast.Name)
        and deep.id == "deep"
    )


def _is_lifecycle_model_copy_return(statement: ast.stmt, state_field: str) -> bool:
    if not isinstance(statement, ast.Return) or not isinstance(statement.value, ast.Call):
        return False
    call = statement.value
    if not _is_super_model_copy(call) or call.args or len(call.keywords) != 1:
        return False
    keyword = call.keywords[0]
    update = keyword.value
    return (
        keyword.arg == "update"
        and isinstance(update, ast.Dict)
        and len(update.keys) == 1
        and isinstance(update.keys[0], ast.Constant)
        and update.keys[0].value == state_field
        and len(update.values) == 1
        and isinstance(update.values[0], ast.Name)
        and update.values[0].id == "target"
    )


def _is_super_model_copy(call: ast.Call) -> bool:
    function = call.func
    return (
        isinstance(function, ast.Attribute)
        and function.attr == "model_copy"
        and isinstance(function.value, ast.Call)
        and isinstance(function.value.func, ast.Name)
        and function.value.func.id == "super"
        and not function.value.args
        and not function.value.keywords
    )
