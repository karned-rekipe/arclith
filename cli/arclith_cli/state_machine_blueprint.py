"""Render explicit, transport-neutral state-machine application features."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent, indent

from arclith_cli.application_blueprint_files import with_package_initializers
from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.project_paths import ProjectPaths
from arclith_cli.rename import EntityNames
from arclith_cli.state_machine_entity import (
    render_state_documentation as _documentation,
    render_state_errors as _errors,
    render_state_model as _state_model,
    state_machine_state_module as _state_module,
    validate_existing_state_field as _validate_existing_state_field,
    validate_state_machine_import_roots as _validate_import_roots,
)
from arclith_cli.state_machine_spec import StateMachineSpec, StateTransitionSpec
from arclith_cli.state_machine_rendering import render_domain_test as _domain_test


def render_state_machine_blueprint(
    paths: ProjectPaths,
    entity: EntityInfo,
    feature: str,
    spec: StateMachineSpec,
    *,
    creating_entity: bool,
) -> dict[Path, str]:
    """Render one explicit state machine; runtime dispatch stays out of the domain."""

    _validate_import_roots(paths)
    if not creating_entity:
        _validate_existing_state_field(paths, entity, spec)
    entity_module = paths.import_path("domain", "models", entity.file_path.stem)
    state_module_name = _state_module(entity)
    state_module = paths.import_path("domain", "models", state_module_name)
    errors_module = paths.import_path("domain", "errors", feature)
    service_module = paths.import_path("domain", "services", feature)
    store_module = paths.import_path("domain", "ports", "outbound", feature)
    ports_prefix = paths.import_path("domain", "ports", "inbound")
    use_cases_prefix = paths.import_path("application", "use_cases")

    files: dict[Path, str] = {
        paths.domain_models / f"{state_module_name}.py": _state_model(
            entity.pascal, spec
        ),
        paths.package_root / "domain" / "errors" / f"{feature}.py": _errors(
            entity.pascal, spec
        ),
        paths.package_root / "domain" / "services" / f"{feature}.py": _service(
            entity.pascal,
            entity_module,
            state_module,
            errors_module,
            spec,
        ),
        paths.package_root
        / "domain"
        / "ports"
        / "outbound"
        / f"{feature}.py": _store_port(entity.pascal, entity_module),
        paths.containers / f"{feature}.py": _container(
            entity.pascal,
            feature,
            service_module,
            store_module,
            ports_prefix,
            use_cases_prefix,
            spec,
        ),
        paths.root / "tests" / "domain" / f"test_{feature}.py": _domain_test(
            paths.package_name or "",
            entity.pascal,
            entity.file_path.stem,
            feature,
            spec,
        ),
        paths.root
        / "tests"
        / "application"
        / f"test_{feature}_use_cases.py": _application_test(
            paths.package_name or "",
            entity.pascal,
            entity.file_path.stem,
            feature,
            spec,
        ),
        paths.root
        / "docs"
        / "blueprints"
        / f"{feature}-state-machine.md": _documentation(entity.pascal, feature, spec),
    }
    for transition in spec.transitions:
        operation = transition.name
        operation_class = EntityNames.from_input(operation).pascal
        port_module = f"{ports_prefix}.{operation}_{entity.snake}"
        files[paths.inbound_ports / f"{operation}_{entity.snake}.py"] = (
            _transition_port(entity.pascal, entity_module, operation_class)
        )
        files[paths.application_use_cases / f"{operation}_{entity.snake}.py"] = (
            _transition_use_case(
                entity.pascal,
                operation,
                operation_class,
                port_module,
                service_module,
                store_module,
                errors_module,
            )
        )
    return with_package_initializers(paths, files)


def _service(
    entity: str,
    entity_module: str,
    state_module: str,
    errors_module: str,
    spec: StateMachineSpec,
) -> str:
    error_names = ",\n    ".join(
        _transition_error(entity, transition) for transition in spec.transitions
    )
    methods = "\n\n".join(
        _transition_methods(entity, spec, transition) for transition in spec.transitions
    )
    return (
        "from enum import Enum as _ArclithEnum\n\n"
        f"from {entity_module} import {entity} as _ArclithEntity\n"
        f"from {state_module} import {entity}State as _ArclithState\n"
        f"from {errors_module} import (\n"
        f"{indent(error_names, '    ')},\n"
        ")\n\n\n"
        f"class {entity}Lifecycle:\n"
        '    """Explicit verbs generated from the canonical transition matrix."""\n\n'
        f"{indent(methods, '    ')}\n"
    )


def _transition_methods(
    entity: str,
    spec: StateMachineSpec,
    transition: StateTransitionSpec,
) -> str:
    allowed = ", ".join(
        f"_ArclithState.{state.upper()}" for state in transition.sources
    )
    if len(transition.sources) == 1:
        allowed += ","
    error = _transition_error(entity, transition)
    return dedent(
        f'''\
            def {transition.name}(
                self,
                entity: _ArclithEntity,
            ) -> _ArclithEntity:
                raw_current = entity.{spec.state_field}
                current_value = (
                    raw_current.value
                    if isinstance(raw_current, _ArclithEnum)
                    else raw_current
                )
                current = _ArclithState(current_value)
                if current not in frozenset(({allowed})):
                    raise {error}(current.value)
                self._ensure_{transition.name}_preconditions(entity)
                target = type(raw_current)(
                    _ArclithState.{transition.target.upper()}.value
                )
                return entity._copy_with_{spec.state_field}(target)

            def _ensure_{transition.name}_preconditions(
                self,
                entity: _ArclithEntity,
            ) -> None:
                """Add project-owned guards here; the state guard already ran."""
                return None
        '''
    ).rstrip()


def _store_port(entity: str, entity_module: str) -> str:
    return dedent(
        f'''\
        from abc import ABC as _ArclithABC
        from abc import abstractmethod as _arclith_abstractmethod
        from uuid import UUID as _ArclithUUID

        from {entity_module} import {entity} as _ArclithEntity


        class {entity}LifecycleStore(_ArclithABC):
            """Persistence boundary with an explicit atomic compare-and-swap contract."""

            @_arclith_abstractmethod
            async def read(self, uuid: _ArclithUUID) -> _ArclithEntity | None:
                raise NotImplementedError

            @_arclith_abstractmethod
            async def compare_and_swap(
                self,
                candidate: _ArclithEntity,
                *,
                expected_version: int,
            ) -> _ArclithEntity:
                """Atomically verify, persist, increment version and update audit time.

                Implementations must raise `{entity}VersionConflictError` if the
                persisted version differs from `expected_version`, populated with
                both `expected_version` and the observed version (`None` if missing).
                """
                raise NotImplementedError
        '''
    )


def _transition_port(entity: str, entity_module: str, operation_class: str) -> str:
    return dedent(
        f"""\
        from abc import ABC as _ArclithABC
        from abc import abstractmethod as _arclith_abstractmethod
        from uuid import UUID as _ArclithUUID

        from pydantic import BaseModel as _ArclithBaseModel
        from pydantic import Field as _ArclithField

        from {entity_module} import {entity} as _ArclithEntity


        class {operation_class}{entity}Command(_ArclithBaseModel):
            uuid: _ArclithUUID
            expected_version: int = _ArclithField(ge=1)
            updated_by: str | None = None


        class {operation_class}{entity}Result(_ArclithBaseModel):
            item: _ArclithEntity


        class {operation_class}{entity}Port(_ArclithABC):
            @_arclith_abstractmethod
            async def execute(
                self,
                command: {operation_class}{entity}Command,
            ) -> {operation_class}{entity}Result:
                raise NotImplementedError
        """
    )


def _transition_use_case(
    entity: str,
    operation: str,
    operation_class: str,
    port_module: str,
    service_module: str,
    store_module: str,
    errors_module: str,
) -> str:
    return dedent(
        f"""\
        from {errors_module} import (
            {entity}NotFoundError,
            {entity}VersionConflictError,
        )
        from {port_module} import (
            {operation_class}{entity}Command,
            {operation_class}{entity}Port,
            {operation_class}{entity}Result,
        )
        from {store_module} import {entity}LifecycleStore
        from {service_module} import {entity}Lifecycle


        class {operation_class}{entity}UseCase({operation_class}{entity}Port):
            def __init__(
                self,
                store: {entity}LifecycleStore,
                lifecycle: {entity}Lifecycle,
            ) -> None:
                self._store = store
                self._lifecycle = lifecycle

            async def execute(
                self,
                command: {operation_class}{entity}Command,
            ) -> {operation_class}{entity}Result:
                current = await self._store.read(command.uuid)
                if current is None:
                    raise {entity}NotFoundError(command.uuid)
                if current.version != command.expected_version:
                    raise {entity}VersionConflictError(
                        expected_version=command.expected_version,
                        observed_version=current.version,
                    )
                candidate = self._lifecycle.{operation}(current).model_copy(
                    update={{"updated_by": command.updated_by}}
                )
                persisted = await self._store.compare_and_swap(
                    candidate,
                    expected_version=command.expected_version,
                )
                return {operation_class}{entity}Result(item=persisted)
        """
    )


def _container(
    entity: str,
    feature: str,
    service_module: str,
    store_module: str,
    ports_prefix: str,
    use_cases_prefix: str,
    spec: StateMachineSpec,
) -> str:
    imports = "\n".join(
        f"from {use_cases_prefix}.{item.name}_{_snake_entity(entity)} import "
        f"{EntityNames.from_input(item.name).pascal}{entity}UseCase"
        for item in spec.transitions
    )
    port_imports = "\n".join(
        f"from {ports_prefix}.{item.name}_{_snake_entity(entity)} import "
        f"{EntityNames.from_input(item.name).pascal}{entity}Port"
        for item in spec.transitions
    )
    fields = "\n".join(
        f"    {item.name}: {EntityNames.from_input(item.name).pascal}{entity}Port"
        for item in spec.transitions
    )
    values = "\n".join(
        f"        {item.name}={EntityNames.from_input(item.name).pascal}{entity}UseCase("
        "store, lifecycle),"
        for item in spec.transitions
    )
    return (
        "from dataclasses import dataclass\n\n"
        f"{imports}\n"
        f"{port_imports}\n"
        f"from {store_module} import {entity}LifecycleStore\n"
        f"from {service_module} import {entity}Lifecycle\n\n\n"
        "@dataclass(frozen=True)\n"
        f"class {entity}LifecycleUseCases:\n"
        f"{fields}\n\n\n"
        f"def build_{feature}_use_cases(\n"
        f"    store: {entity}LifecycleStore,\n"
        f") -> {entity}LifecycleUseCases:\n"
        '    """Compose explicit transitions around an application-owned CAS store."""\n'
        f"    lifecycle = {entity}Lifecycle()\n"
        f"    return {entity}LifecycleUseCases(\n"
        f"{values}\n"
        "    )\n"
    )


def _application_test(
    package: str,
    entity: str,
    entity_module: str,
    feature: str,
    spec: StateMachineSpec,
) -> str:
    prefix = f"{package}." if package else ""
    entry = next(
        transition
        for transition in spec.transitions
        if spec.initial_state in transition.sources
    )
    operation_class = EntityNames.from_input(entry.name).pascal
    forbidden = next(
        (
            (transition, state)
            for transition in spec.transitions
            for state in spec.states
            if state not in transition.sources
        ),
        None,
    )
    used_transitions = [entry]
    if forbidden is not None and forbidden[0].name != entry.name:
        used_transitions.append(forbidden[0])
    error_names = [f"{entity}NotFoundError", f"{entity}VersionConflictError"]
    if forbidden is not None:
        error_names.insert(1, f"{entity}TransitionNotAllowedError")
    error_imports = "\n".join(f"            {name}," for name in error_names)
    command_imports = "\n".join(
        "        from "
        f"{prefix}domain.ports.inbound.{transition.name}_{_snake_entity(entity)} "
        f"import {EntityNames.from_input(transition.name).pascal}{entity}Command"
        for transition in used_transitions
    )
    forbidden_test = ""
    if forbidden is not None:
        forbidden_transition, forbidden_state = forbidden
        forbidden_class = EntityNames.from_input(forbidden_transition.name).pascal
        forbidden_test = dedent(
            f"""\


            @pytest.mark.asyncio
            async def test_forbidden_transition_does_not_persist_partial_state() -> None:
                item = make_{_snake_entity(entity)}("{forbidden_state}")
                store = FakeStore(item)
                use_cases = build_{feature}_use_cases(store)

                with pytest.raises({entity}TransitionNotAllowedError):
                    await use_cases.{forbidden_transition.name}.execute(
                        {forbidden_class}{entity}Command(
                            uuid=item.uuid,
                            expected_version=item.version,
                        )
                    )

                assert store.writes == 0
                stored = await store.read(item.uuid)
                assert stored is not None
                assert _persisted_state(stored.{spec.state_field}) == "{forbidden_state}"
            """
        )
    return (
        dedent(
            f"""\
        from datetime import UTC as _ArclithUTC
        from datetime import datetime as _ArclithDatetime
        from enum import Enum as _ArclithEnum
        from uuid import UUID as _ArclithUUID

        import pytest

        from {prefix}domain.errors.{feature} import (
{error_imports}
        )
        from {prefix}domain.models.{entity_module} import {entity} as _ArclithEntity
{command_imports}
        from {prefix}domain.ports.outbound.{feature} import {entity}LifecycleStore
        from {prefix}infrastructure.containers.{feature} import (
            build_{feature}_use_cases,
        )


        def _state_value(state: str) -> object:
            annotation = _ArclithEntity.model_fields["{spec.state_field}"].annotation
            if isinstance(annotation, type) and issubclass(annotation, _ArclithEnum):
                return annotation(state)
            return state


        def _persisted_state(value: object) -> object:
            return value.value if isinstance(value, _ArclithEnum) else value


        def make_{_snake_entity(entity)}(
            state: str = "{spec.initial_state}",
        ) -> _ArclithEntity:
            # Isolate lifecycle tests without guessing required business fields.
            return _ArclithEntity.model_construct(
                {spec.state_field}=_state_value(state),
            )


        class FakeStore({entity}LifecycleStore):
            def __init__(
                self,
                item: _ArclithEntity | None,
                *,
                observed_version_at_compare: int | None = None,
            ) -> None:
                self.item = item
                self.observed_version_at_compare = observed_version_at_compare
                self.writes = 0

            async def read(self, uuid: _ArclithUUID) -> _ArclithEntity | None:
                if self.item is None or self.item.uuid != uuid:
                    return None
                return self.item

            async def compare_and_swap(
                self,
                candidate: _ArclithEntity,
                *,
                expected_version: int,
            ) -> _ArclithEntity:
                observed_version = (
                    self.observed_version_at_compare
                    if self.observed_version_at_compare is not None
                    else (None if self.item is None else self.item.version)
                )
                if observed_version != expected_version:
                    raise {entity}VersionConflictError(
                        expected_version=expected_version,
                        observed_version=observed_version,
                    )
                self.writes += 1
                self.item = candidate.model_copy(
                    update={{
                        "updated_at": _ArclithDatetime.now(_ArclithUTC),
                        "version": expected_version + 1,
                    }}
                )
                return self.item


        @pytest.mark.asyncio
        async def test_transition_loads_applies_and_compare_and_swaps() -> None:
            item = make_{_snake_entity(entity)}()
            store = FakeStore(item)
            use_cases = build_{feature}_use_cases(store)

            result = await use_cases.{entry.name}.execute(
                {operation_class}{entity}Command(
                    uuid=item.uuid,
                    expected_version=item.version,
                    updated_by="actor-1",
                )
            )

            expected = _state_value("{entry.target}")
            assert result.item.{spec.state_field} == expected
            assert type(result.item.{spec.state_field}) is type(expected)
            assert result.item.version == 2
            assert result.item.updated_by == "actor-1"
            assert store.writes == 1


        @pytest.mark.asyncio
        async def test_missing_stale_and_raced_versions_are_distinct() -> None:
            missing = FakeStore(None)
            missing_use_cases = build_{feature}_use_cases(missing)
            command = {operation_class}{entity}Command(
                uuid=_ArclithUUID("01951234-5678-7abc-8ef0-123456789abc"),
                expected_version=1,
            )
            with pytest.raises(
                {entity}NotFoundError,
                match=str(command.uuid),
            ) as missing_error:
                await missing_use_cases.{entry.name}.execute(command)
            assert missing_error.value.uuid == command.uuid

            item = make_{_snake_entity(entity)}()
            stale = FakeStore(item)
            stale_use_cases = build_{feature}_use_cases(stale)
            with pytest.raises({entity}VersionConflictError) as stale_error:
                await stale_use_cases.{entry.name}.execute(
                    command.model_copy(update={{"uuid": item.uuid, "expected_version": 2}})
                )
            assert stale_error.value.expected_version == 2
            assert stale_error.value.observed_version == 1
            assert stale.writes == 0

            raced = FakeStore(item, observed_version_at_compare=2)
            raced_use_cases = build_{feature}_use_cases(raced)
            with pytest.raises({entity}VersionConflictError) as race_error:
                await raced_use_cases.{entry.name}.execute(
                    command.model_copy(update={{"uuid": item.uuid}})
                )
            assert race_error.value.expected_version == 1
            assert race_error.value.observed_version == 2
            assert raced.writes == 0
        """
        )
        + forbidden_test
    )


def _transition_error(entity: str, transition: StateTransitionSpec) -> str:
    return f"{EntityNames.from_input(transition.name).pascal}{entity}NotAllowedError"


def _snake_entity(entity: str) -> str:
    return EntityNames.from_input(entity).snake
