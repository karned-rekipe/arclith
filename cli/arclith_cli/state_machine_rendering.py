"""Render supporting entity, documentation and test state-machine files."""

from __future__ import annotations

from textwrap import dedent, indent

from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.project_paths import ProjectPaths
from arclith_cli.rename import EntityNames
from arclith_cli.state_machine_spec import StateMachineSpec, StateTransitionSpec


def state_machine_state_module(entity: EntityInfo) -> str:
    """Return the dedicated generated lifecycle-enum module stem."""

    return f"{entity.snake}_lifecycle_state"


def render_state_machine_entity(
    paths: ProjectPaths,
    entity: EntityInfo,
    spec: StateMachineSpec,
) -> str:
    """Render the state field atomically with a new entity profile."""

    state_module = paths.import_path(
        "domain", "models", state_machine_state_module(entity)
    )
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

            def __init__(
                self,
                *,
                expected_version: int,
                observed_version: int | None,
            ) -> None:
                self.expected_version = expected_version
                self.observed_version = observed_version
                observed = (
                    "missing" if observed_version is None else str(observed_version)
                )
                super().__init__(
                    f"Persisted version {{observed}} differs from expected version "
                    f"{{expected_version}}"
                )


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
        "enregistrer le candidat, incrémenter la version et actualiser l'audit.\n"
        f"Toute course doit lever `{entity}VersionConflictError` avec les versions\n"
        "`expected_version` et `observed_version` (`None` si l'agrégat a disparu).\n"
        "La vérification préalable du use case améliore le diagnostic local, mais ne\n"
        "remplace jamais ce CAS dans un adapter multi-processus.\n\n"
        "Cette machine décrit l'état métier d'un agrégat. Elle n'est ni un CRUD\n"
        "générique, ni l'état d'exécution d'un workflow durable. Aucun transport,\n"
        "broker, événement publié ou moteur de workflow n'est ajouté implicitement.\n\n"
        "Avant de renommer ou supprimer un état en production, inventorier les\n"
        "valeurs historiques et prévoir une migration explicite. Le manifeste\n"
        "version 2 embarque la configuration résolue et ses digests ; il ne dépend\n"
        "pas du chemin local de la spec utilisée à l'installation.\n"
    )


def render_domain_test(
    package: str,
    entity: str,
    entity_module: str,
    feature: str,
    spec: StateMachineSpec,
) -> str:
    """Render lifecycle-domain tests against the entity's declared state type."""

    prefix = f"{package}." if package else ""
    error_imports = ",\n    ".join(
        _transition_error(entity, transition) for transition in spec.transitions
    )
    error_items = "\n".join(
        f'    "{item.name}": {_transition_error(entity, item)},'
        for item in spec.transitions
    )
    matrix = "\n".join(
        f'    ("{state}", "{transition.name}", '
        + (f'"{transition.target}"),' if state in transition.sources else "None),")
        for transition in spec.transitions
        for state in spec.states
    )
    first = spec.transitions[0]
    return (
        "from enum import Enum as _ArclithEnum\n\n"
        "import pytest\n"
        "from pydantic import ValidationError as _ArclithValidationError\n\n"
        f"from {prefix}domain.errors.{feature} import (\n"
        f"{indent(error_imports, '    ')},\n"
        ")\n"
        f"from {prefix}domain.models.{entity_module} import {entity} as _ArclithEntity\n"
        f"from {prefix}domain.services.{feature} import {entity}Lifecycle\n\n\n"
        "ERRORS = {\n"
        f"{error_items}\n"
        "}\n\n"
        "TRANSITION_MATRIX = (\n"
        f"{matrix}\n"
        ")\n\n\n"
        f"def _state_value(state: str) -> object:\n"
        f'    annotation = _ArclithEntity.model_fields["{spec.state_field}"].annotation\n'
        "    if isinstance(annotation, type) and issubclass(annotation, _ArclithEnum):\n"
        "        return annotation(state)\n"
        "    return state\n\n\n"
        "def _persisted_state(value: object) -> object:\n"
        "    return value.value if isinstance(value, _ArclithEnum) else value\n\n\n"
        f"def make_{_snake_entity(entity)}(\n"
        f'    state: str = "{spec.initial_state}",\n'
        f") -> _ArclithEntity:\n"
        '    """Isolate lifecycle tests without guessing required business fields."""\n'
        f"    return _ArclithEntity.model_construct(\n"
        f"        {spec.state_field}=_state_value(state),\n"
        "    )\n\n\n"
        '@pytest.mark.parametrize(("state", "operation", "target"), TRANSITION_MATRIX)\n'
        f"def test_{feature}_transition_matrix(\n"
        "    state: str,\n"
        "    operation: str,\n"
        "    target: str | None,\n"
        ") -> None:\n"
        f"    lifecycle = {entity}Lifecycle()\n"
        f"    original = make_{_snake_entity(entity)}(state)\n"
        "    transition = getattr(lifecycle, operation)\n\n"
        "    if target is None:\n"
        "        with pytest.raises(ERRORS[operation]):\n"
        "            transition(original)\n"
        f"        assert _persisted_state(original.{spec.state_field}) == state\n"
        "        return\n\n"
        "    changed = transition(original)\n"
        "    expected = _state_value(target)\n"
        f"    assert changed.{spec.state_field} == expected\n"
        f"    assert type(changed.{spec.state_field}) is type(expected)\n"
        f"    assert _persisted_state(original.{spec.state_field}) == state\n\n\n"
        f"def test_{feature}_{spec.state_field}_rejects_arbitrary_assignment() -> None:\n"
        f"    entity = make_{_snake_entity(entity)}()\n\n"
        '    with pytest.raises(_ArclithValidationError, match="frozen"):\n'
        f'        setattr(entity, "{spec.state_field}", '
        f'_state_value("{first.target}"))\n'
        '    with pytest.raises(ValueError, match="lifecycle"):\n'
        f"        entity.model_copy(\n"
        f'            update={{"{spec.state_field}": _state_value("{first.target}")}}\n'
        "        )\n\n\n"
        f"def test_{feature}_business_precondition_extension_is_explicit() -> None:\n"
        f"    class GuardedLifecycle({entity}Lifecycle):\n"
        f"        def _ensure_{first.name}_preconditions(\n"
        "            self, entity: _ArclithEntity\n"
        "        ) -> None:\n"
        '            raise RuntimeError("project-owned guard")\n\n'
        f'    entity = make_{_snake_entity(entity)}("{first.sources[0]}")\n'
        '    with pytest.raises(RuntimeError, match="project-owned guard"):\n'
        f"        GuardedLifecycle().{first.name}(entity)\n"
    )


def _transition_error(entity: str, transition: StateTransitionSpec) -> str:
    return f"{EntityNames.from_input(transition.name).pascal}{entity}NotAllowedError"


def _snake_entity(entity: str) -> str:
    return EntityNames.from_input(entity).snake
