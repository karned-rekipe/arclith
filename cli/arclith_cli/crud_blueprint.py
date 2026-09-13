from pathlib import Path
from textwrap import dedent

from arclith_cli.application_blueprint_files import with_package_initializers
from arclith_cli.crud_asset_rendering import (
    render_crud_documentation,
    render_crud_test,
)
from arclith_cli.crud_contract_rendering import (
    render_create_port,
    render_update_port,
)
from arclith_cli.entity_contract import inspect_entity_contract
from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.project_paths import ProjectPaths


def render_crud_blueprint(
    paths: ProjectPaths,
    entity: EntityInfo,
    feature: str,
) -> dict[Path, str]:
    entity_module = paths.import_path("domain", "models", entity.file_path.stem)
    contract = inspect_entity_contract(paths, entity)
    errors_module = paths.import_path("domain", "errors", feature)
    ports_prefix = paths.import_path("domain", "ports", "inbound")
    use_cases_prefix = paths.import_path("application", "use_cases")
    base = {
        paths.package_root / "domain" / "errors" / f"{feature}.py": _errors(
            entity.pascal
        ),
        paths.inbound_ports / f"create_{feature}.py": render_create_port(
            entity.pascal, entity_module, contract
        ),
        paths.inbound_ports / f"get_{feature}.py": _get_port(
            entity.pascal, entity_module
        ),
        paths.inbound_ports / f"list_{feature}.py": _list_port(
            entity.pascal, entity_module
        ),
        paths.inbound_ports / f"update_{feature}.py": render_update_port(
            entity.pascal, entity_module, contract
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
        paths.root
        / "tests"
        / "application"
        / f"test_{feature}_crud.py": render_crud_test(
            paths.package_name or "", entity.pascal, feature, contract
        ),
        paths.root
        / "docs"
        / "blueprints"
        / f"{feature}-crud.md": render_crud_documentation(
            entity.pascal, feature, contract
        ),
    }
    return with_package_initializers(paths, base)


def _errors(entity: str) -> str:
    return dedent(
        f'''\
        class {entity}NotFoundError(LookupError):
            """Raised when the requested {entity} does not exist or was deleted."""


        class {entity}VersionConflictError(RuntimeError):
            """Raised when an update targets a stale optimistic-lock version."""
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
                current_values = {{
                    **(current.model_extra or {{}}),
                    **{{
                        field_name: getattr(current, field_name)
                        for field_name in type(current).model_fields
                    }},
                }}
                candidate = type(current).model_validate(
                    {{
                        **current_values,
                        **changes,
                        "version": command.version,
                    }},
                    by_name=True,
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
