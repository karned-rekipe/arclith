"""Render and validate the entity-facing state-machine contract."""

from __future__ import annotations

import ast
from pathlib import Path

from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.immutable_record_scaffold import is_entity_base
from arclith_cli.import_origins import project_shadowed_top_level_modules
from arclith_cli.project_paths import ProjectPaths
from arclith_cli.state_machine_contract import (
    class_scope_bindings,
    class_scope_binds_name,
    class_shadowed_contract_dependencies,
    state_copy_is_controlled,
    statement_binds_name,
)
from arclith_cli.state_machine_rendering import (
    render_state_documentation,
    render_state_errors,
    render_state_machine_entity,
    render_state_model,
    state_machine_state_module,
)
from arclith_cli.state_machine_spec import StateMachineSpec
from arclith_cli.state_machine_types import (
    enum_members as _enum_members,
    is_imported_symbol as _is_imported_symbol,
    resolve_enum_declaration as _resolve_enum_declaration,
    resolve_enum_values as _resolve_enum_values,
    resolve_literal_values as _resolve_literal_values,
)

__all__ = [
    "STATE_MACHINE_EXISTING_ENTITY_VALIDATION_VERSION",
    "render_state_documentation",
    "render_state_errors",
    "render_state_machine_entity",
    "render_state_model",
    "state_machine_state_module",
    "validate_state_machine_import_roots",
]


# Bump whenever ``validate_existing_state_field`` accepts or rejects new forms.
STATE_MACHINE_EXISTING_ENTITY_VALIDATION_VERSION = 16


def validate_state_machine_import_roots(paths: ProjectPaths) -> None:
    """Reject project modules that can shadow trusted generated imports."""

    shadowed_modules = project_shadowed_top_level_modules(
        paths,
        (
            "abc",
            "arclith",
            "collections",
            "dataclasses",
            "datetime",
            "enum",
            "pydantic",
            "pytest",
            "typing",
            "typing_extensions",
            "uuid",
        ),
    )
    if shadowed_modules:
        raise ValueError(
            "Project shadows trusted state contract modules at an import root: "
            + ", ".join(sorted(shadowed_modules))
        )


def validate_existing_state_field(
    paths: ProjectPaths,
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
    model = models[0]
    if (
        len(model.bases) != 1
        or not is_entity_base(tree, model.bases[0], model.lineno)
        or model.decorator_list
        or model.keywords
    ):
        raise ValueError(
            "state-machine requires one direct Arclith Entity base without "
            "mixins, decorators or class keywords"
        )
    fields = [
        statement
        for statement in model.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and statement.target.id == spec.state_field
    ]
    if not fields:
        raise ValueError(
            f"Entity {entity.pascal} must declare typed field {spec.state_field!r}; "
            "add it explicitly, then replay the command"
        )
    if len(fields) != 1:
        raise ValueError(
            f"Entity field {entity.pascal}.{spec.state_field} must be typed as "
            "a statically inspectable string-valued Enum/StrEnum or Literal "
            "containing exactly the declared states"
        )
    field = fields[0]
    if class_scope_bindings(model, spec.state_field) != (field,):
        raise ValueError(
            f"Entity field {entity.pascal}.{spec.state_field} must have exactly one "
            "class-scope binding; later assignments can remove its protection"
        )
    shadowed_dependencies = class_shadowed_contract_dependencies(model, field)
    if shadowed_dependencies:
        raise ValueError(
            f"Entity {entity.pascal} shadows state contract dependencies in its "
            "class scope: " + ", ".join(sorted(shadowed_dependencies))
        )
    literal_states = _resolve_literal_values(
        field.annotation,
        tree=tree,
        entity_file=entity.file_path,
    )
    enum_states = _resolve_enum_values(
        field.annotation,
        tree=tree,
        entity_file=entity.file_path,
    )
    expected_states = set(spec.states)
    if literal_states != expected_states and enum_states != expected_states:
        raise ValueError(
            f"Entity field {entity.pascal}.{spec.state_field} must be typed as "
            "a statically inspectable string-valued Enum/StrEnum or Literal "
            "containing exactly the declared states"
        )
    if not _state_assignment_is_protected(model, field, tree=tree):
        raise ValueError(
            f"Entity field {entity.pascal}.{spec.state_field} must reject assignment "
            "without coercing enum values; use ConfigDict(validate_assignment=True) "
            "with Field(..., frozen=True) and keep use_enum_values disabled"
        )
    if not _state_default_is_valid(
        field,
        literal_states=literal_states,
        enum_states=enum_states,
        tree=tree,
        entity_file=entity.file_path,
    ):
        raise ValueError(
            f"Entity field {entity.pascal}.{spec.state_field} must use its declared "
            "enum type or a declared Literal value as its static default, or be required"
        )
    if not state_copy_is_controlled(model, spec.state_field, tree=tree):
        raise ValueError(
            f"Entity field {entity.pascal}.{spec.state_field} must reject generic "
            f"model_copy updates and expose a private _copy_with_{spec.state_field} "
            "method for the lifecycle"
        )


def _state_assignment_is_protected(
    model: ast.ClassDef,
    field: ast.AnnAssign,
    *,
    tree: ast.Module,
) -> bool:
    if class_scope_binds_name(model, "__setattr__"):
        return False
    config_bindings = [
        statement for statement in model.body if _binds_model_config(statement)
    ]
    if len(config_bindings) != 1:
        return False
    config = config_bindings[0]
    if not (
        isinstance(config, ast.Assign)
        and len(config.targets) == 1
        and isinstance(config.targets[0], ast.Name)
        and isinstance(config.value, ast.Call)
        and _is_pydantic_callable(config.value.func, "ConfigDict", tree)
    ):
        return False
    if any(option.arg is None for option in config.value.keywords):
        return False
    config_values = {
        option.arg: option.value
        for option in config.value.keywords
        if option.arg is not None
    }
    use_enum_values = config_values.get("use_enum_values")
    if use_enum_values is not None and not (
        isinstance(use_enum_values, ast.Constant) and use_enum_values.value is False
    ):
        return False
    config_options = {
        option.arg: option.value.value
        for option in config.value.keywords
        if option.arg is not None
        and isinstance(option.value, ast.Constant)
        and isinstance(option.value.value, bool)
    }
    if config_options.get("use_enum_values") is True:
        return False
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


def _binds_model_config(statement: ast.stmt) -> bool:
    return statement_binds_name(statement, "model_config")


def _state_default_is_valid(
    field: ast.AnnAssign,
    *,
    literal_states: set[str] | None,
    enum_states: set[str] | None,
    tree: ast.Module,
    entity_file: Path,
) -> bool:
    inspectable, default = _static_field_default(field.value, tree=tree)
    if not inspectable:
        return False
    if default is None:
        return True
    if literal_states is not None:
        return (
            isinstance(default, ast.Constant)
            and isinstance(default.value, str)
            and default.value in literal_states
        )
    if enum_states is None or not isinstance(default, ast.Attribute):
        return False
    annotation_enum = _resolve_enum_declaration(
        field.annotation,
        tree=tree,
        entity_file=entity_file,
    )
    default_enum = _resolve_enum_declaration(
        default.value,
        tree=tree,
        entity_file=entity_file,
    )
    if annotation_enum is None or default_enum is None:
        return False
    annotation_class, annotation_tree, annotation_file = annotation_enum
    default_class, _, default_file = default_enum
    members = _enum_members(annotation_class, annotation_tree)
    return (
        annotation_file.resolve() == default_file.resolve()
        and annotation_class.name == default_class.name
        and members is not None
        and default.attr in members
    )


def _static_field_default(
    value: ast.expr | None,
    *,
    tree: ast.Module,
) -> tuple[bool, ast.expr | None]:
    if value is None:
        return True, None
    default = value
    if isinstance(default, ast.Call):
        if not _is_pydantic_callable(default.func, "Field", tree):
            return False, None
        if any(option.arg is None for option in default.keywords):
            return False, None
        default_keywords = [
            option.value for option in default.keywords if option.arg == "default"
        ]
        if (
            len(default.args) > 1
            or len(default_keywords) > 1
            or (default.args and default_keywords)
            or any(option.arg == "default_factory" for option in default.keywords)
        ):
            return False, None
        if default.args:
            default = default.args[0]
        elif default_keywords:
            default = default_keywords[0]
        else:
            return True, None
    if isinstance(default, ast.Constant) and default.value is Ellipsis:
        return True, None
    return True, default


def _is_pydantic_callable(
    expression: ast.expr,
    symbol: str,
    tree: ast.Module,
) -> bool:
    return _is_imported_symbol(
        expression,
        symbols=frozenset({symbol}),
        modules=frozenset({"pydantic"}),
        tree=tree,
    )
