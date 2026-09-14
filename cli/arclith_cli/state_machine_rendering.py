"""Render the entity-facing files of a state-machine blueprint."""

from __future__ import annotations

from textwrap import dedent

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


def _transition_error(entity: str, transition: StateTransitionSpec) -> str:
    return f"{EntityNames.from_input(transition.name).pascal}{entity}NotAllowedError"
