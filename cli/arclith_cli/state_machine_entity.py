"""Render and validate the entity-facing state-machine contract."""

from __future__ import annotations

import ast
from pathlib import Path

from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.import_origins import project_shadowed_top_level_modules
from arclith_cli.module_bindings import (
    module_bindings_before,
    node_line_or_module_end,
    uncertain_module_bindings_before,
)
from arclith_cli.project_paths import ProjectPaths
from arclith_cli.state_machine_contract import (
    class_scope_bindings,
    class_scope_binds_name,
    class_shadowed_contract_dependencies,
    state_copy_is_controlled,
)
from arclith_cli.state_machine_rendering import (
    render_state_documentation,
    render_state_errors,
    render_state_machine_entity,
    render_state_model,
    state_machine_state_module,
)
from arclith_cli.state_machine_spec import StateMachineSpec

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
STATE_MACHINE_EXISTING_ENTITY_VALIDATION_VERSION = 9


def validate_state_machine_import_roots(paths: ProjectPaths) -> None:
    """Reject project modules that can shadow trusted generated imports."""

    shadowed_modules = project_shadowed_top_level_modules(
        paths,
        ("enum", "pydantic", "typing", "typing_extensions"),
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
    if annotation.id in uncertain_module_bindings_before(
        tree,
        node_line_or_module_end(annotation, tree),
    ):
        return None
    bindings = _top_level_bindings_before(tree, annotation.id, annotation)
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
        (item for item in binding.names if (item.asname or item.name) == annotation.id),
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
    resolved = _resolve_enum_declaration(
        annotation,
        tree=tree,
        entity_file=entity_file,
        visited=visited,
    )
    if resolved is None:
        return None
    declaration, declaration_tree, _ = resolved
    return _enum_values(declaration, declaration_tree)


def _resolve_enum_declaration(
    annotation: ast.expr,
    *,
    tree: ast.Module,
    entity_file: Path,
    visited: frozenset[tuple[Path, str]] = frozenset(),
) -> tuple[ast.ClassDef, ast.Module, Path] | None:
    if not isinstance(annotation, ast.Name):
        return None
    symbol = annotation.id
    key = (entity_file, symbol)
    if key in visited:
        return None
    if symbol in uncertain_module_bindings_before(
        tree,
        node_line_or_module_end(annotation, tree),
    ):
        return None
    bindings = _top_level_bindings_before(tree, symbol, annotation)
    if len(bindings) != 1:
        return None
    binding = bindings[0]
    if isinstance(binding, ast.ClassDef):
        if _enum_values(binding, tree) is None:
            return None
        return binding, tree, entity_file
    alias_value = _alias_value(binding, symbol)
    if alias_value is not None:
        return _resolve_enum_declaration(
            alias_value,
            tree=tree,
            entity_file=entity_file,
            visited=visited | {key},
        )
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
    return _resolve_enum_declaration(
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
    members = _enum_members(declaration, tree)
    return set(members.values()) if members is not None else None


def _enum_members(
    declaration: ast.ClassDef,
    tree: ast.Module,
) -> dict[str, str] | None:
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
    members: dict[str, str] = {}
    declarations: set[str] = set()
    for statement in declaration.body:
        if isinstance(statement, ast.Pass) or (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if statement.decorator_list or statement.name in declarations:
                return None
            declarations.add(statement.name)
            continue
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
            return None
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            return None
        if member_name in declarations:
            return None
        declarations.add(member_name)
        members[member_name] = value.value
    return members or None


def _top_level_bindings_before(
    tree: ast.Module,
    symbol: str,
    reference: ast.AST,
) -> list[ast.stmt]:
    boundary = node_line_or_module_end(reference, tree)
    return [
        statement
        for statement in tree.body
        if statement.lineno < boundary and symbol in _bound_names(statement)
    ]


def _bound_names(statement: ast.stmt) -> set[str]:
    if isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return {statement.name}
    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        return {item.asname or item.name.split(".", 1)[0] for item in statement.names}
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
        binding = module_bindings_before(
            tree,
            node_line_or_module_end(expression, tree),
        ).get(expression.id)
        if binding is None:
            return False
        statement, alias = binding
        return (
            isinstance(statement, ast.ImportFrom)
            and statement in tree.body
            and statement.level == 0
            and statement.module in modules
            and alias.name in symbols
            and (alias.asname or alias.name) == expression.id
        )
    if not (
        isinstance(expression, ast.Attribute)
        and expression.attr in symbols
        and isinstance(expression.value, ast.Name)
    ):
        return False
    module_alias = expression.value.id
    binding = module_bindings_before(
        tree,
        node_line_or_module_end(expression, tree),
    ).get(module_alias)
    if binding is None:
        return False
    statement, alias = binding
    return (
        isinstance(statement, ast.Import)
        and statement in tree.body
        and alias.name in modules
        and (alias.asname or alias.name) == module_alias
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
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return statement.name == "model_config"
    if "model_config" in _bound_names(statement):
        return True
    return any(
        isinstance(node, ast.Name)
        and node.id == "model_config"
        and isinstance(node.ctx, (ast.Store, ast.Del))
        for node in ast.walk(statement)
    )


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
