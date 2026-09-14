"""Render and validate the entity-facing state-machine contract."""

from __future__ import annotations

import ast
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
        "n'existe ni setter générique du statut ni moteur runtime\n"
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
        fields[0].annotation, entity.pascal, spec
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


def _compatible_state_annotation(
    annotation: ast.expr,
    entity: str,
    spec: StateMachineSpec,
) -> bool:
    reference = ast.unparse(annotation)
    if reference == f"{entity}State" or reference.endswith(f".{entity}State"):
        return True
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


def _transition_error(entity: str, transition: StateTransitionSpec) -> str:
    return f"{EntityNames.from_input(transition.name).pascal}{entity}NotAllowedError"
