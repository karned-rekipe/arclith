"""Render and validate the entity-facing state-machine contract."""

from __future__ import annotations

import ast
from pathlib import Path
from textwrap import dedent

from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.project_paths import ProjectPaths
from arclith_cli.rename import EntityNames
from arclith_cli.state_machine_spec import StateMachineSpec, StateTransitionSpec


def render_state_machine_entity(
    paths: ProjectPaths,
    entity: EntityInfo,
    spec: StateMachineSpec,
) -> str:
    """Render the state field atomically with a new entity profile."""

    state_module = paths.import_path("domain", "models", f"{entity.snake}_state")
    return dedent(
        f'''\
        from __future__ import annotations

        from collections.abc import Mapping
        from typing import Any, Self

        from pydantic import ConfigDict, Field

        from arclith.domain.models.entity import Entity
        from {state_module} import {entity.pascal}State


        class {entity.pascal}(Entity):
            """TODO: add business fields without exposing a generic status setter."""

            model_config = ConfigDict(validate_assignment=True)

            {spec.state_field}: {entity.pascal}State = Field(
                default={entity.pascal}State.{spec.initial_state.upper()},
                frozen=True,
            )

            def model_copy(
                self,
                *,
                update: Mapping[str, Any] | None = None,
                deep: bool = False,
            ) -> Self:
                if update is not None and "{spec.state_field}" in update:
                    raise ValueError(
                        "{spec.state_field} changes must use the generated lifecycle"
                    )
                return super().model_copy(update=update, deep=deep)

            def _copy_with_{spec.state_field}(
                self,
                target: {entity.pascal}State,
            ) -> Self:
                """Controlled state replacement used only by the lifecycle service."""
                return super().model_copy(update={{"{spec.state_field}": target}})

            # Example business field:
            # title: str = Field(min_length=1, max_length=140)
        '''
    )


def render_state_model(entity: str, spec: StateMachineSpec) -> str:
    members = "\n".join(f'    {state.upper()} = "{state}"' for state in spec.states)
    return (
        "from enum import StrEnum\n\n\n"
        f"class {entity}State(StrEnum):\n"
        f'    """Stable persisted values for the {entity} business lifecycle."""\n\n'
        f"{members}\n"
    )


def render_state_errors(entity: str, spec: StateMachineSpec) -> str:
    transition_errors = "\n\n".join(
        dedent(
            f'''\
            class {_transition_error(entity, transition)}({entity}TransitionNotAllowedError):
                """Raised when `{transition.name}` is requested from a forbidden state."""

                operation = "{transition.name}"
            '''
        ).rstrip()
        for transition in spec.transitions
    )
    base = dedent(
        f'''\
        class {entity}LifecycleError(Exception):
            """Base error for the generated {entity} lifecycle."""


        class {entity}NotFoundError({entity}LifecycleError, LookupError):
            """Raised when a transition targets a missing aggregate."""


        class {entity}VersionConflictError({entity}LifecycleError, RuntimeError):
            """Raised when compare-and-swap observes another persisted version."""


        class {entity}TransitionNotAllowedError({entity}LifecycleError):
            """Base error for an explicitly forbidden business transition."""

            operation = "unknown"

            def __init__(self, current_state: object) -> None:
                super().__init__(
                    f"{{self.operation}} is not allowed from state {{current_state}}"
                )
        '''
    )
    return base + "\n" + transition_errors + "\n"


def render_state_documentation(
    entity: str,
    feature: str,
    spec: StateMachineSpec,
) -> str:
    transitions = "\n".join(
        f"- `{item.name}` : {', '.join(item.sources)} -> `{item.target}`"
        for item in spec.transitions
    )
    return (
        f"# Blueprint state-machine `{feature}`\n\n"
        f"Cette feature applique le blueprint `state-machine` version 1 à `{entity}`.\n"
        f"Le champ `{spec.state_field}` démarre à `{spec.initial_state}` et ses valeurs\n"
        f"persistées sont définies par `{entity}State`.\n\n"
        "## Transitions explicites\n\n"
        f"{transitions}\n\n"
        "Chaque verbe possède son propre port inbound et son propre use case. Il\n"
        "n'existe ni setter ni mise à jour `model_copy` générique du statut, ni\n"
        "moteur runtime\n"
        '`transition("nom")`. Le service de domaine vérifie d\'abord la matrice,\n'
        "puis appelle `_ensure_<verbe>_preconditions`, point d'extension local pour\n"
        "les gardes métier du projet. Une transition interdite lève une erreur typée\n"
        "et retourne sans muter l'agrégat reçu.\n\n"
        f"Le container exige un `{entity}LifecycleStore`. Son opération\n"
        "`compare_and_swap` doit vérifier atomiquement la version persistée,\n"
        "enregistrer le candidat, incrémenter la version et actualiser l'audit. La\n"
        "vérification préalable du use case améliore le diagnostic local, mais ne\n"
        "remplace jamais ce CAS dans un adapter multi-processus.\n\n"
        "Cette machine décrit l'état métier d'un agrégat. Elle n'est ni un CRUD\n"
        "générique, ni l'état d'exécution d'un workflow durable. Aucun transport,\n"
        "broker, événement publié ou moteur de workflow n'est ajouté implicitement.\n\n"
        "Avant de renommer ou supprimer un état en production, inventorier les\n"
        "valeurs historiques et prévoir une migration explicite. Le manifeste\n"
        "version 2 embarque la configuration résolue et ses digests ; il ne dépend\n"
        "pas du chemin local de la spec utilisée à l'installation.\n"
    )


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
        entity.pascal,
        spec,
        tree=tree,
        entity_file=entity.file_path,
    ):
        raise ValueError(
            f"Entity field {entity.pascal}.{spec.state_field} must be typed as "
            f"{entity.pascal}State or Literal containing exactly the declared states"
        )
    if not _state_assignment_is_protected(models[0], fields[0]):
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
    entity: str,
    spec: StateMachineSpec,
    *,
    tree: ast.Module,
    entity_file: Path,
) -> bool:
    reference = ast.unparse(annotation)
    if reference == f"{entity}State" or reference.endswith(f".{entity}State"):
        return _resolve_enum_values(
            annotation,
            tree=tree,
            entity_file=entity_file,
        ) == set(spec.states)
    if not isinstance(annotation, ast.Subscript):
        return False
    root = ast.unparse(annotation.value)
    if root not in {"Literal", "typing.Literal"}:
        return False
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
    return len(literal_states) == len(values) and literal_states == set(spec.states)


def _resolve_enum_values(
    annotation: ast.expr,
    *,
    tree: ast.Module,
    entity_file: Path,
) -> set[str] | None:
    if not isinstance(annotation, ast.Name):
        return None
    symbol = annotation.id
    local = _enum_values(tree, symbol)
    if local is not None:
        return local
    for statement in tree.body:
        if not isinstance(statement, ast.ImportFrom):
            continue
        imported = next(
            (item for item in statement.names if (item.asname or item.name) == symbol),
            None,
        )
        if imported is None:
            continue
        module_file = _resolve_module_file(entity_file, statement)
        if module_file is None:
            return None
        try:
            imported_tree = ast.parse(
                module_file.read_text(encoding="utf-8"),
                filename=str(module_file),
            )
        except (OSError, SyntaxError):
            return None
        return _enum_values(imported_tree, imported.name)
    return None


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


def _enum_values(tree: ast.Module, symbol: str) -> set[str] | None:
    declaration = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == symbol
        ),
        None,
    )
    if declaration is None or not any(
        ast.unparse(base).rsplit(".", 1)[-1] in {"Enum", "StrEnum"}
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


def _state_assignment_is_protected(
    model: ast.ClassDef,
    field: ast.AnnAssign,
) -> bool:
    config_options: dict[str, bool] = {}
    for statement in model.body:
        if not isinstance(statement, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == "model_config"
            for target in statement.targets
        ):
            continue
        if isinstance(statement.value, ast.Call) and ast.unparse(
            statement.value.func
        ).endswith("ConfigDict"):
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
    if not isinstance(value, ast.Call) or not ast.unparse(value.func).endswith("Field"):
        return False
    return any(
        option.arg == "frozen"
        and isinstance(option.value, ast.Constant)
        and option.value.value is True
        for option in value.keywords
    )


def _state_copy_is_controlled(model: ast.ClassDef, state_field: str) -> bool:
    methods = {
        statement.name: statement
        for statement in model.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    public_copy = methods.get("model_copy")
    lifecycle_copy = methods.get(f"_copy_with_{state_field}")
    if public_copy is None or lifecycle_copy is None:
        return False
    public_literals = {
        node.value
        for node in ast.walk(public_copy)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    lifecycle_literals = {
        node.value
        for node in ast.walk(lifecycle_copy)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    return (
        state_field in public_literals
        and any(isinstance(node, ast.Raise) for node in ast.walk(public_copy))
        and state_field in lifecycle_literals
        and any(
            isinstance(node, ast.Attribute) and node.attr == "model_copy"
            for node in ast.walk(lifecycle_copy)
        )
    )


def _transition_error(entity: str, transition: StateTransitionSpec) -> str:
    return f"{EntityNames.from_input(transition.name).pascal}{entity}NotAllowedError"
