from pathlib import Path
from textwrap import dedent

from arclith_cli.application_blueprint_files import with_package_initializers
from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.immutable_record_scaffold import inspect_immutable_record
from arclith_cli.project_paths import ProjectPaths


def render_append_only_blueprint(
    paths: ProjectPaths,
    entity: EntityInfo,
    feature: str,
) -> dict[Path, str]:
    """Render a transport-neutral append-only application feature."""

    has_business_fields = inspect_immutable_record(entity)
    entity_module = paths.import_path("domain", "models", entity.file_path.stem)
    port_module = paths.import_path("domain", "ports", "inbound", f"append_{feature}")
    use_case_module = paths.import_path("application", "use_cases", f"append_{feature}")
    files = {
        paths.inbound_ports / f"append_{feature}.py": _append_port(
            entity.pascal,
            entity_module,
        ),
        paths.application_use_cases / f"append_{feature}.py": _append_use_case(
            entity.pascal,
            entity_module,
            port_module,
        ),
        paths.containers / f"{feature}.py": _container(
            entity.pascal,
            entity_module,
            port_module,
            use_case_module,
            feature,
        ),
        paths.root / "tests" / "application" / f"test_{feature}_append_only.py": _test(
            paths.package_name or "",
            entity.pascal,
            entity.file_path.stem,
            feature,
            has_business_fields=has_business_fields,
        ),
        paths.root
        / "docs"
        / "blueprints"
        / f"{feature}-append-only.md": _documentation(entity.pascal, feature),
    }
    return with_package_initializers(paths, files)


def _append_port(entity: str, entity_module: str) -> str:
    return dedent(
        f"""\
        from abc import ABC, abstractmethod

        from pydantic import BaseModel, Field

        from arclith.domain.ports.outbound.append_only_store import AppendStatus
        from {entity_module} import {entity}


        class Append{entity}Command(BaseModel):
            record: {entity}
            idempotency_key: str = Field(min_length=1, max_length=255)


        class Append{entity}Result(BaseModel):
            record: {entity}
            status: AppendStatus


        class Append{entity}Port(ABC):
            @abstractmethod
            async def execute(
                self, command: Append{entity}Command
            ) -> Append{entity}Result:
                raise NotImplementedError
        """
    )


def _append_use_case(entity: str, entity_module: str, port_module: str) -> str:
    return dedent(
        f"""\
        from arclith.domain.ports.outbound.append_only_store import AppendOnlyStore

        from {entity_module} import {entity}
        from {port_module} import (
            Append{entity}Command,
            Append{entity}Port,
            Append{entity}Result,
        )


        class Append{entity}UseCase(Append{entity}Port):
            def __init__(self, store: AppendOnlyStore[{entity}]) -> None:
                self._store = store

            async def execute(
                self, command: Append{entity}Command
            ) -> Append{entity}Result:
                outcome = await self._store.append(
                    command.record,
                    idempotency_key=command.idempotency_key,
                )
                return Append{entity}Result(
                    record=outcome.record,
                    status=outcome.status,
                )
        """
    )


def _container(
    entity: str,
    entity_module: str,
    port_module: str,
    use_case_module: str,
    feature: str,
) -> str:
    return dedent(
        f'''\
        from dataclasses import dataclass

        from arclith.domain.ports.outbound.append_only_store import AppendOnlyStore

        from {entity_module} import {entity}
        from {port_module} import Append{entity}Port
        from {use_case_module} import Append{entity}UseCase


        @dataclass(frozen=True)
        class {entity}UseCases:
            append: Append{entity}Port


        def build_{feature}_use_cases(
            store: AppendOnlyStore[{entity}],
        ) -> {entity}UseCases:
            """Compose append-only use cases around an explicitly selected store."""
            return {entity}UseCases(append=Append{entity}UseCase(store))
        '''
    )


def _test(
    package: str,
    entity: str,
    model_module: str,
    feature: str,
    *,
    has_business_fields: bool,
) -> str:
    prefix = f"{package}." if package else ""
    if has_business_fields:
        return _business_record_test(prefix, entity, model_module, feature)
    return dedent(
        f'''\
        from datetime import UTC, datetime

        import pytest

        from arclith.adapters.outbound.memory.append_only_store import (
            InMemoryAppendOnlyStore,
        )
        from arclith.domain.ports.outbound.append_only_store import AppendStatus

        from {prefix}domain.models.{model_module} import {entity}
        from {prefix}domain.ports.inbound.append_{feature} import (
            Append{entity}Command,
        )
        from {prefix}infrastructure.containers.{feature} import (
            build_{feature}_use_cases,
        )


        @pytest.mark.asyncio
        async def test_{feature}_append_is_idempotent() -> None:
            store = InMemoryAppendOnlyStore[{entity}]()
            use_cases = build_{feature}_use_cases(store)
            record = {entity}(
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
            command = Append{entity}Command(
                record=record,
                idempotency_key="{feature}-001",
            )

            first = await use_cases.append.execute(command)
            duplicate = await use_cases.append.execute(command)

            assert first.status is AppendStatus.APPENDED
            assert duplicate.status is AppendStatus.DUPLICATE
            assert duplicate.record == first.record
            assert len(store.inspect_records()) == 1
        '''
    )


def _business_record_test(
    prefix: str, entity: str, model_module: str, feature: str
) -> str:
    return dedent(
        f"""\
        from arclith.adapters.outbound.memory.append_only_store import (
            InMemoryAppendOnlyStore,
        )
        from arclith.domain.models.immutable_record import ImmutableRecord

        from {prefix}domain.models.{model_module} import {entity}
        from {prefix}domain.ports.inbound.append_{feature} import (
            Append{entity}Command,
            Append{entity}Port,
        )
        from {prefix}infrastructure.containers.{feature} import (
            build_{feature}_use_cases,
        )


        def test_{feature}_contract_and_empty_store() -> None:
            # Supply representative business facts in additional scenario tests.
            store = InMemoryAppendOnlyStore[{entity}]()
            use_cases = build_{feature}_use_cases(store)

            assert issubclass({entity}, ImmutableRecord)
            assert {entity}.model_config["frozen"] is True
            assert Append{entity}Command.model_fields["record"].annotation is {entity}
            assert isinstance(use_cases.append, Append{entity}Port)
            assert store.inspect_records() == ()
        """
    )


def _documentation(entity: str, feature: str) -> str:
    return dedent(
        f"""\
        # Blueprint append-only `{feature}`

        Cette feature applique le blueprint `append-only` version 1 au record
        immuable `{entity}`. Elle déclare une seule opération : `append`.

        Le modèle hérite d'`ImmutableRecord` : `occurred_at` représente le temps
        métier explicite, tandis que le store attribue `recorded_at` en UTC au
        premier append. Corriger un fait signifie ajouter un nouveau fait
        d'invalidation ou de compensation, jamais réécrire l'ancien.

        Le use case dépend uniquement d'`AppendOnlyStore[{entity}]`. Le container
        exige que l'appelant fournisse explicitement l'adapter ; pour les tests,
        `InMemoryAppendOnlyStore` est déterministe mais ni durable ni distribué.

        Une même clé d'idempotence et le même contenu canonique renvoient
        `duplicate`. Réutiliser cette clé avec un contenu différent lève
        `IdempotencyConflict`. L'empreinte SHA-256 trie les clés JSON et exclut
        `recorded_at`, attribué par le store. Elle inclut l'identité, le temps
        métier et tous les champs métier du record.

        Aucune query, route FastAPI, surface FastMCP, binding RabbitMQ ou node
        LangGraph n'est créé. Une projection de lecture et un store durable sont
        des capabilities séparées à concevoir explicitement.

        Pydantic `frozen` bloque la réaffectation des champs. Les collections
        imbriquées peuvent rester mutables ; le store protège ses faits par des
        copies profondes à l'entrée et à la sortie. Privilégiez des tuples et des
        sous-modèles frozen. Les tests générés ne devinent pas les champs métier
        requis : ajoutez des scénarios avec vos propres exemples représentatifs.
        """
    )
