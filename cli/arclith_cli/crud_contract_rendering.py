"""Render CRUD write-side application contracts from an entity snapshot."""

from __future__ import annotations

import ast
from textwrap import dedent

from arclith_cli.entity_contract import EntityContract


def render_create_port(
    entity: str,
    entity_module: str,
    contract: EntityContract,
) -> str:
    imports = _port_imports(
        entity,
        entity_module,
        contract,
        include_uuid=False,
        require_field=False,
    )
    rendered = dedent(
        f'''\
        from __future__ import annotations

        __PORT_IMPORTS__


        class Create{entity}Command(BaseModel):
            """Validated writable fields snapshotted from the entity."""

        __ENTITY_FIELDS__


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
    return rendered.replace("__PORT_IMPORTS__", imports).replace(
        "__ENTITY_FIELDS__",
        _class_fields(contract.create_fields),
    )


def render_update_port(
    entity: str,
    entity_module: str,
    contract: EntityContract,
) -> str:
    imports = _port_imports(
        entity,
        entity_module,
        contract,
        include_uuid=True,
        require_field=True,
    )
    rendered = dedent(
        f'''\
        from __future__ import annotations

        __PORT_IMPORTS__


        class Update{entity}Command(BaseModel):
            """Optimistic partial update of the entity's writable fields."""

            uuid: UUID
            version: int = Field(ge=1)
        __ENTITY_FIELDS__


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
    return rendered.replace("__PORT_IMPORTS__", imports).replace(
        "__ENTITY_FIELDS__",
        _class_fields(contract.update_fields),
    )


def _class_fields(fields: tuple[str, ...]) -> str:
    if not fields:
        return "    pass"
    return "\n".join(f"    {field}" for field in fields)


def _port_imports(
    entity: str,
    entity_module: str,
    contract: EntityContract,
    *,
    include_uuid: bool,
    require_field: bool,
) -> str:
    remaining: list[str] = []
    pydantic_names = [ast.alias(name="BaseModel")]
    if require_field:
        pydantic_names.append(ast.alias(name="Field"))
    entity_names = [ast.alias(name=entity)]
    for rendered in contract.imports:
        statement = ast.parse(rendered).body[0]
        if isinstance(statement, ast.ImportFrom) and statement.module == "pydantic":
            pydantic_names.extend(statement.names)
        elif (
            isinstance(statement, ast.ImportFrom) and statement.module == entity_module
        ):
            entity_names.extend(statement.names)
        else:
            remaining.append(rendered)

    lines = ["from abc import ABC, abstractmethod"]
    if include_uuid:
        lines.append("from uuid import UUID")
    lines.extend(remaining)
    lines.append(_from_import("pydantic", pydantic_names))
    lines.append(_from_import(entity_module, entity_names))
    return "\n".join(lines)


def _from_import(module: str, names: list[ast.alias]) -> str:
    unique = {(alias.name, alias.asname): alias for alias in names}
    statement = ast.ImportFrom(
        module=module,
        names=[
            unique[key]
            for key in sorted(unique, key=lambda item: (item[0], item[1] or ""))
        ],
        level=0,
    )
    return ast.unparse(statement)
