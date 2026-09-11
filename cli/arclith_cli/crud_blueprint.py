from pathlib import Path
from textwrap import dedent

from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.project_paths import ProjectPaths


def render_crud_blueprint(
    paths: ProjectPaths,
    entity: EntityInfo,
    feature: str,
) -> dict[Path, str]:
    entity_module = paths.import_path("domain", "models", entity.file_path.stem)
    errors_module = paths.import_path("domain", "errors", feature)
    ports_prefix = paths.import_path("domain", "ports", "inbound")
    use_cases_prefix = paths.import_path("application", "use_cases")
    base = {
        paths.package_root / "domain" / "errors" / f"{feature}.py": _errors(
            entity.pascal
        ),
        paths.inbound_ports / f"create_{feature}.py": _create_port(
            entity.pascal, entity_module
        ),
        paths.inbound_ports / f"get_{feature}.py": _get_port(
            entity.pascal, entity_module
        ),
        paths.inbound_ports / f"list_{feature}.py": _list_port(
            entity.pascal, entity_module
        ),
        paths.inbound_ports / f"update_{feature}.py": _update_port(
            entity.pascal, entity_module
        ),
        paths.inbound_ports / f"delete_{feature}.py": _delete_port(entity.pascal),
        paths.application_use_cases / f"create_{feature}.py": _create_use_case(
            entity.pascal,
            entity_module,
            f"{ports_prefix}.create_{feature}",
        ),
        paths.application_use_cases / f"get_{feature}.py": _get_use_case(
            entity.pascal,
            entity_module,
            f"{ports_prefix}.get_{feature}",
            errors_module,
        ),
        paths.application_use_cases / f"list_{feature}.py": _list_use_case(
            entity.pascal,
            entity_module,
            f"{ports_prefix}.list_{feature}",
        ),
        paths.application_use_cases / f"update_{feature}.py": _update_use_case(
            entity.pascal,
            entity_module,
            f"{ports_prefix}.update_{feature}",
            errors_module,
        ),
        paths.application_use_cases / f"delete_{feature}.py": _delete_use_case(
            entity.pascal,
            entity_module,
            f"{ports_prefix}.delete_{feature}",
            errors_module,
        ),
        paths.containers / f"{feature}.py": _container(
            entity.pascal,
            entity_module,
            ports_prefix,
            use_cases_prefix,
            feature,
        ),
        paths.root / "tests" / "application" / f"test_{feature}_crud.py": _test(
            paths.package_name or "", entity.pascal, feature
        ),
        paths.root / "docs" / "blueprints" / f"{feature}-crud.md": _documentation(
            entity.pascal, feature
        ),
    }
    return _with_package_initializers(paths, base)


def _with_package_initializers(
    paths: ProjectPaths,
    files: dict[Path, str],
) -> dict[Path, str]:
    result = dict(files)
    for path in tuple(files):
        for parent in path.parents:
            if parent in {paths.root, paths.package_root.parent}:
                break
            if parent.is_relative_to(paths.package_root) or parent.is_relative_to(
                paths.root / "tests"
            ):
                result.setdefault(parent / "__init__.py", "")
    return result


def _errors(entity: str) -> str:
    return dedent(
        f'''\
        class {entity}NotFoundError(LookupError):
            """Raised when the requested {entity} does not exist or was deleted."""


        class {entity}VersionConflictError(RuntimeError):
            """Raised when an update targets a stale optimistic-lock version."""
        '''
    )


def _create_port(entity: str, entity_module: str) -> str:
    return dedent(
        f'''\
        from abc import ABC, abstractmethod

        from pydantic import BaseModel

        from {entity_module} import {entity}


        class Create{entity}Command(BaseModel):
            """Validated creation fields; add the entity's writable business fields."""

            pass


        class Create{entity}Result(BaseModel):
            item: {entity}


        class Create{entity}Port(ABC):
            @abstractmethod
            async def execute(
                self, command: Create{entity}Command
            ) -> Create{entity}Result:
                raise NotImplementedError
        '''
    )


def _get_port(entity: str, entity_module: str) -> str:
    return dedent(
        f"""\
        from abc import ABC, abstractmethod
        from uuid import UUID

        from pydantic import BaseModel

        from {entity_module} import {entity}


        class Get{entity}Query(BaseModel):
            uuid: UUID


        class Get{entity}Result(BaseModel):
            item: {entity}


        class Get{entity}Port(ABC):
            @abstractmethod
            async def execute(self, query: Get{entity}Query) -> Get{entity}Result:
                raise NotImplementedError
        """
    )


def _list_port(entity: str, entity_module: str) -> str:
    return dedent(
        f"""\
        from abc import ABC, abstractmethod

        from pydantic import BaseModel, Field

        from {entity_module} import {entity}


        class List{entity}Query(BaseModel):
            offset: int = Field(default=0, ge=0)
            limit: int = Field(default=100, ge=1, le=1000)


        class List{entity}Result(BaseModel):
            items: list[{entity}]
            total: int
            offset: int
            limit: int


        class List{entity}Port(ABC):
            @abstractmethod
            async def execute(self, query: List{entity}Query) -> List{entity}Result:
                raise NotImplementedError
        """
    )


def _update_port(entity: str, entity_module: str) -> str:
    return dedent(
        f'''\
        from abc import ABC, abstractmethod
        from uuid import UUID

        from pydantic import BaseModel, Field

        from {entity_module} import {entity}


        class Update{entity}Command(BaseModel):
            """Optimistic update; add the entity's writable business fields."""

            uuid: UUID
            version: int = Field(ge=1)


        class Update{entity}Result(BaseModel):
            item: {entity}


        class Update{entity}Port(ABC):
            @abstractmethod
            async def execute(
                self, command: Update{entity}Command
            ) -> Update{entity}Result:
                raise NotImplementedError
        '''
    )


def _delete_port(entity: str) -> str:
    return dedent(
        f"""\
        from abc import ABC, abstractmethod
        from uuid import UUID

        from pydantic import BaseModel


        class Delete{entity}Command(BaseModel):
            uuid: UUID
            deleted_by: str | None = None


        class Delete{entity}Result(BaseModel):
            deleted: bool


        class Delete{entity}Port(ABC):
            @abstractmethod
            async def execute(
                self, command: Delete{entity}Command
            ) -> Delete{entity}Result:
                raise NotImplementedError
        """
    )


def _create_use_case(entity: str, entity_module: str, port_module: str) -> str:
    return dedent(
        f"""\
        from arclith.application.services.base_service import BaseService

        from {entity_module} import {entity}
        from {port_module} import (
            Create{entity}Command,
            Create{entity}Port,
            Create{entity}Result,
        )


        class Create{entity}UseCase(Create{entity}Port):
            def __init__(self, service: BaseService[{entity}]) -> None:
                self._service = service

            async def execute(
                self, command: Create{entity}Command
            ) -> Create{entity}Result:
                entity = {entity}.model_validate(
                    command.model_dump(exclude_unset=True), by_name=True
                )
                return Create{entity}Result(item=await self._service.create(entity))
        """
    )


def _get_use_case(
    entity: str,
    entity_module: str,
    port_module: str,
    errors_module: str,
) -> str:
    return dedent(
        f"""\
        from arclith.application.services.base_service import BaseService

        from {entity_module} import {entity}
        from {errors_module} import {entity}NotFoundError
        from {port_module} import Get{entity}Port, Get{entity}Query, Get{entity}Result


        class Get{entity}UseCase(Get{entity}Port):
            def __init__(self, service: BaseService[{entity}]) -> None:
                self._service = service

            async def execute(self, query: Get{entity}Query) -> Get{entity}Result:
                item = await self._service.read(query.uuid)
                if item is None:
                    raise {entity}NotFoundError(str(query.uuid))
                return Get{entity}Result(item=item)
        """
    )


def _list_use_case(entity: str, entity_module: str, port_module: str) -> str:
    return dedent(
        f"""\
        from arclith.application.services.base_service import BaseService

        from {entity_module} import {entity}
        from {port_module} import List{entity}Port, List{entity}Query, List{entity}Result


        class List{entity}UseCase(List{entity}Port):
            def __init__(self, service: BaseService[{entity}]) -> None:
                self._service = service

            async def execute(self, query: List{entity}Query) -> List{entity}Result:
                items, total = await self._service.find_page(query.offset, query.limit)
                return List{entity}Result(
                    items=items,
                    total=total,
                    offset=query.offset,
                    limit=query.limit,
                )
        """
    )


def _update_use_case(
    entity: str,
    entity_module: str,
    port_module: str,
    errors_module: str,
) -> str:
    return dedent(
        f"""\
        from arclith.application.services.base_service import BaseService

        from {entity_module} import {entity}
        from {errors_module} import (
            {entity}NotFoundError,
            {entity}VersionConflictError,
        )
        from {port_module} import (
            Update{entity}Command,
            Update{entity}Port,
            Update{entity}Result,
        )


        class Update{entity}UseCase(Update{entity}Port):
            def __init__(self, service: BaseService[{entity}]) -> None:
                self._service = service

            async def execute(
                self, command: Update{entity}Command
            ) -> Update{entity}Result:
                current = await self._service.read(command.uuid)
                if current is None:
                    raise {entity}NotFoundError(str(command.uuid))
                if current.version != command.version:
                    raise {entity}VersionConflictError(
                        f"expected version {{current.version}}, got {{command.version}}"
                    )
                changes = command.model_dump(
                    exclude={{"uuid", "version"}}, exclude_unset=True
                )
                candidate = type(current).model_validate(
                    {{
                        **current.model_dump(),
                        **changes,
                        "version": command.version,
                    }}
                )
                return Update{entity}Result(
                    item=await self._service.update(candidate)
                )
        """
    )


def _delete_use_case(
    entity: str,
    entity_module: str,
    port_module: str,
    errors_module: str,
) -> str:
    return dedent(
        f"""\
        from arclith.application.services.base_service import BaseService

        from {entity_module} import {entity}
        from {errors_module} import {entity}NotFoundError
        from {port_module} import (
            Delete{entity}Command,
            Delete{entity}Port,
            Delete{entity}Result,
        )


        class Delete{entity}UseCase(Delete{entity}Port):
            def __init__(self, service: BaseService[{entity}]) -> None:
                self._service = service

            async def execute(
                self, command: Delete{entity}Command
            ) -> Delete{entity}Result:
                if await self._service.read(command.uuid) is None:
                    raise {entity}NotFoundError(str(command.uuid))
                await self._service.delete(command.uuid, command.deleted_by)
                return Delete{entity}Result(deleted=True)
        """
    )


def _container(
    entity: str,
    entity_module: str,
    ports_prefix: str,
    use_cases_prefix: str,
    feature: str,
) -> str:
    return dedent(
        f'''\
        from dataclasses import dataclass

        from arclith import Arclith
        from arclith.application.services.base_service import BaseService

        from {use_cases_prefix}.create_{feature} import Create{entity}UseCase
        from {use_cases_prefix}.delete_{feature} import Delete{entity}UseCase
        from {use_cases_prefix}.get_{feature} import Get{entity}UseCase
        from {use_cases_prefix}.list_{feature} import List{entity}UseCase
        from {use_cases_prefix}.update_{feature} import Update{entity}UseCase
        from {entity_module} import {entity}
        from {ports_prefix}.create_{feature} import Create{entity}Port
        from {ports_prefix}.delete_{feature} import Delete{entity}Port
        from {ports_prefix}.get_{feature} import Get{entity}Port
        from {ports_prefix}.list_{feature} import List{entity}Port
        from {ports_prefix}.update_{feature} import Update{entity}Port


        @dataclass(frozen=True)
        class {entity}UseCases:
            create: Create{entity}Port
            get: Get{entity}Port
            list: List{entity}Port
            update: Update{entity}Port
            delete: Delete{entity}Port


        def build_{feature}_use_cases(arclith: Arclith) -> {entity}UseCases:
            """Compose one shared CRUD service without selecting a concrete adapter."""
            service = BaseService[{entity}](
                arclith.repository({entity}),
                arclith.logger,
                arclith.config.soft_delete.retention_days,
            )
            return {entity}UseCases(
                create=Create{entity}UseCase(service),
                get=Get{entity}UseCase(service),
                list=List{entity}UseCase(service),
                update=Update{entity}UseCase(service),
                delete=Delete{entity}UseCase(service),
            )
        '''
    )


def _test(package: str, entity: str, feature: str) -> str:
    prefix = f"{package}." if package else ""
    return dedent(
        f"""\
        import pytest

        from arclith import Arclith

        from {prefix}domain.errors.{feature} import {entity}NotFoundError
        from {prefix}domain.ports.inbound.create_{feature} import (
            Create{entity}Command,
        )
        from {prefix}domain.ports.inbound.delete_{feature} import (
            Delete{entity}Command,
        )
        from {prefix}domain.ports.inbound.get_{feature} import Get{entity}Query
        from {prefix}domain.ports.inbound.list_{feature} import List{entity}Query
        from {prefix}domain.ports.inbound.update_{feature} import (
            Update{entity}Command,
        )
        from {prefix}infrastructure.containers.{feature} import (
            build_{feature}_use_cases,
        )


        @pytest.mark.asyncio
        async def test_{feature}_crud_uses_the_configured_repository() -> None:
            use_cases = build_{feature}_use_cases(Arclith("config"))

            created = await use_cases.create.execute(Create{entity}Command())
            found = await use_cases.get.execute(
                Get{entity}Query(uuid=created.item.uuid)
            )
            page = await use_cases.list.execute(List{entity}Query())
            updated = await use_cases.update.execute(
                Update{entity}Command(
                    uuid=created.item.uuid,
                    version=created.item.version,
                )
            )
            deleted = await use_cases.delete.execute(
                Delete{entity}Command(uuid=created.item.uuid)
            )

            assert found.item == created.item
            assert page.items == [created.item]
            assert page.total == 1
            assert updated.item.version == 2
            assert deleted.deleted is True
            with pytest.raises({entity}NotFoundError):
                await use_cases.get.execute(Get{entity}Query(uuid=created.item.uuid))
        """
    )


def _documentation(entity: str, feature: str) -> str:
    return dedent(
        f"""\
        # Blueprint CRUD `{feature}`

        Cette feature applique le blueprint CRUD version 1 à l'entité `{entity}`.

        Opérations déclarées : `create`, `get`, `list`, `update`, `delete`.

        Les ports inbound et les use cases sont détenus par ce projet. Complétez les
        champs métier de `Create{entity}Command` et `Update{entity}Command` avant de
        publier un contrat de transport. Le container compose les primitives CRUD
        Arclith avec le repository choisi par la configuration ; il ne sélectionne
        aucun adapter concret.

        Les projections FastAPI, FastMCP, RabbitMQ ou LangGraph sont des décisions
        séparées. Après installation explicite de FastAPI, projetez ce CRUD avec :

        `arclith-cli expose-feature {feature} --via fastapi --path /v1/<collection>`

        La CLI traduit NotFound et VersionConflict en 404 et 409 au bord HTTP.
        N'exposez que les opérations compatibles avec le transport visé.
        """
    )
