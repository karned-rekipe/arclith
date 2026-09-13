"""Render CRUD write-side application contracts from an entity snapshot."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from textwrap import dedent

from arclith_cli.entity_contract import EntityContract


def render_create_port(
    entity: str,
    entity_module: str,
    contract: EntityContract,
) -> str:
    _reject_generated_name_collisions(entity, contract, "Create")
    support = _support_names(entity, contract, include_uuid=False)
    imports = _port_imports(
        entity,
        entity_module,
        contract,
        support,
        include_uuid=False,
        require_field=False,
    )
    rendered = dedent(
        f'''\
        from __future__ import annotations

        __PORT_IMPORTS__


        class Create{entity}Command({support.base_model}):
            """Validated writable fields snapshotted from the entity."""

        __ENTITY_FIELDS__


        class Create{entity}Result({support.base_model}):
            item: {entity}


        class Create{entity}Port({support.abc}):
            @{support.abstractmethod}
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
    _reject_generated_name_collisions(entity, contract, "Update")
    support = _support_names(entity, contract, include_uuid=True)
    imports = _port_imports(
        entity,
        entity_module,
        contract,
        support,
        include_uuid=True,
        require_field=True,
    )
    rendered = dedent(
        f'''\
        from __future__ import annotations

        __PORT_IMPORTS__


        class Update{entity}Command({support.base_model}):
            """Optimistic partial update of the entity's writable fields."""

            uuid: {support.uuid}
            version: int = {support.field}(ge=1)
        __ENTITY_FIELDS__


        class Update{entity}Result({support.base_model}):
            item: {entity}


        class Update{entity}Port({support.abc}):
            @{support.abstractmethod}
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


@dataclass(frozen=True)
class _SupportNames:
    base_model: str
    field: str
    uuid: str
    abc: str
    abstractmethod: str


def _support_names(
    entity: str,
    contract: EntityContract,
    *,
    include_uuid: bool,
) -> _SupportNames:
    unavailable = _bound_import_names(contract.imports) | {entity}
    field = contract.support_field_name
    unavailable.add(field)
    base_model = _available_name("_ArclithCrudBaseModel", unavailable)
    unavailable.add(base_model)
    uuid = _available_name("_ArclithCrudUUID", unavailable)
    if include_uuid:
        unavailable.add(uuid)
    abc = _available_name("_ArclithCrudABC", unavailable)
    unavailable.add(abc)
    abstractmethod = _available_name("_arclith_crud_abstractmethod", unavailable)
    return _SupportNames(base_model, field, uuid, abc, abstractmethod)


def _bound_import_names(imports: tuple[str, ...]) -> set[str]:
    names: set[str] = set()
    for rendered in imports:
        statement = ast.parse(rendered).body[0]
        if isinstance(statement, ast.Import):
            names.update(
                alias.asname or alias.name.split(".")[0] for alias in statement.names
            )
        elif isinstance(statement, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in statement.names)
        elif isinstance(statement, ast.Assign):
            names.update(
                target.id
                for target in statement.targets
                if isinstance(target, ast.Name)
            )
        elif isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            names.add(statement.target.id)
        elif isinstance(statement, ast.TypeAlias) and isinstance(
            statement.name, ast.Name
        ):
            names.add(statement.name.id)
    return names


def _available_name(preferred: str, unavailable: set[str]) -> str:
    candidate = preferred
    while candidate in unavailable:
        candidate += "_"
    return candidate


def _reject_generated_name_collisions(
    entity: str,
    contract: EntityContract,
    operation: str,
) -> None:
    generated = {
        f"{operation}{entity}Command",
        f"{operation}{entity}Result",
        f"{operation}{entity}Port",
    }
    collisions = generated & _bound_import_names(contract.imports)
    if collisions:
        raise ValueError(
            "Entity field imports collide with generated CRUD contract names: "
            + ", ".join(sorted(collisions))
            + "; alias the imported entity field type before generating the blueprint"
        )


def _port_imports(
    entity: str,
    entity_module: str,
    contract: EntityContract,
    support: _SupportNames,
    *,
    include_uuid: bool,
    require_field: bool,
) -> str:
    remaining: list[str] = []
    pydantic_names = [ast.alias(name="BaseModel", asname=support.base_model)]
    if require_field:
        pydantic_names.append(ast.alias(name="Field", asname=support.field))
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

    lines = [
        f"from abc import ABC as {support.abc}, "
        f"abstractmethod as {support.abstractmethod}"
    ]
    if include_uuid:
        lines.append(f"from uuid import UUID as {support.uuid}")
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
