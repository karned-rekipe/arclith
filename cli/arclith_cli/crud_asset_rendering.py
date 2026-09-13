"""Render project-owned tests and documentation for a CRUD blueprint."""

from textwrap import dedent

from arclith_cli.entity_contract import EntityContract


def render_crud_test(
    package: str,
    entity: str,
    feature: str,
    contract: EntityContract,
) -> str:
    if contract.field_names:
        return _business_entity_test(package, entity, feature, contract.field_names)
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


def _business_entity_test(
    package: str,
    entity: str,
    feature: str,
    field_names: tuple[str, ...],
) -> str:
    prefix = f"{package}." if package else ""
    business_fields = "{" + ", ".join(repr(name) for name in sorted(field_names)) + "}"
    return dedent(
        f"""\
        from uuid import uuid4

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
        async def test_{feature}_crud_contract_and_empty_repository() -> None:
            use_cases = build_{feature}_use_cases(Arclith("config"))
            missing_uuid = uuid4()
            business_fields = {business_fields}

            page = await use_cases.list.execute(List{entity}Query())

            assert set(Create{entity}Command.model_fields) == business_fields
            assert set(Update{entity}Command.model_fields) == (
                {{"uuid", "version"}} | business_fields
            )
            assert page.items == []
            assert page.total == 0
            with pytest.raises({entity}NotFoundError):
                await use_cases.get.execute(Get{entity}Query(uuid=missing_uuid))
            with pytest.raises({entity}NotFoundError):
                await use_cases.update.execute(
                    Update{entity}Command(uuid=missing_uuid, version=1)
                )
            with pytest.raises({entity}NotFoundError):
                await use_cases.delete.execute(
                    Delete{entity}Command(uuid=missing_uuid)
                )
        """
    )


def render_crud_documentation(
    entity: str,
    feature: str,
    contract: EntityContract,
) -> str:
    if contract.field_names:
        fields = ", ".join(f"`{name}`" for name in contract.field_names)
        customization = (
            f"Les champs métier {fields} ont été copiés depuis `{entity}` dans "
            f"`Create{entity}Command` et rendus optionnels en présence dans "
            f"`Update{entity}Command`. Les contraintes Pydantic restent actives. "
            "Ces commandes deviennent propriété du projet et ne seront pas "
            "écrasées par une relance."
        )
    else:
        customization = (
            f"Aucun champ métier n'était déclaré sur `{entity}` au moment de "
            f"l'application du blueprint. Complétez `Create{entity}Command` et "
            f"`Update{entity}Command` si vous ajoutez ensuite des champs au modèle."
        )
    return dedent(
        f"""\
        # Blueprint CRUD `{feature}`

        Cette feature applique le blueprint CRUD version 1 à l'entité `{entity}`.

        Opérations déclarées : `create`, `get`, `list`, `update`, `delete`.

        {customization}

        Les ports inbound et les use cases sont détenus par ce projet. Le container
        compose les primitives CRUD Arclith avec le repository choisi par la
        configuration ; il ne sélectionne aucun adapter concret.

        Les projections FastAPI, FastMCP, RabbitMQ ou LangGraph sont des décisions
        séparées. Après installation explicite de FastAPI, projetez ce CRUD avec :

        `arclith-cli expose-feature {feature} --via fastapi --path /v1/<collection>`

        La CLI traduit NotFound et VersionConflict en 404 et 409 au bord HTTP.
        N'exposez que les opérations compatibles avec le transport visé.
        """
    )
