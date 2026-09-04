import ast
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest

import arclith.domain as domain_package
from arclith.adapters.outbound.relational import (
    RelationalColumn,
    RelationalEntityMapper,
    RelationalIndex,
    RelationalMapperRegistry,
)
from arclith.domain.models.entity import Entity


class UserAccount(Entity):
    email: str
    display_name: str


class UserAccountMapper:
    entity_class = UserAccount
    table_name = "user_accounts"
    columns = (
        RelationalColumn("uuid", "uuid", primary_key=True),
        RelationalColumn("email", "string", unique=True, indexed=True),
        RelationalColumn("display_name", "string"),
        RelationalColumn("created_at", "datetime", indexed=True),
        RelationalColumn("updated_at", "datetime"),
        RelationalColumn("deleted_at", "datetime", nullable=True, indexed=True),
        RelationalColumn("version", "integer"),
    )
    indexes = (
        RelationalIndex(
            "ix_user_accounts_display_created",
            ("display_name", "created_at"),
        ),
    )

    def to_record(self, entity: UserAccount) -> Mapping[str, Any]:
        return {
            "uuid": entity.uuid,
            "email": entity.email,
            "display_name": entity.display_name,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
            "deleted_at": entity.deleted_at,
            "version": entity.version,
        }

    def from_record(self, record: Mapping[str, Any]) -> UserAccount:
        return UserAccount(**dict(record))


def test_empty_registry_resolves_none_and_require_fails() -> None:
    registry = RelationalMapperRegistry()

    assert registry.resolve(UserAccount) is None
    with pytest.raises(ValueError, match=r"registered mapper.*UserAccount"):
        registry.require(UserAccount)


def test_registry_registers_exact_entity_mapper_and_round_trips() -> None:
    mapper = UserAccountMapper()
    registry = RelationalMapperRegistry().register(mapper)
    account = UserAccount(email="ada@example.net", display_name="Ada")

    resolved = registry.require(UserAccount)
    restored = resolved.from_record(resolved.to_record(account))

    assert resolved is mapper
    assert restored == account


def test_registry_rejects_mapper_collision() -> None:
    registry = RelationalMapperRegistry().register(UserAccountMapper())

    with pytest.raises(ValueError, match=r"already registered.*UserAccount"):
        registry.register(UserAccountMapper())


@pytest.mark.parametrize(
    "declaration",
    [
        lambda: RelationalColumn("unsafe-name", "string"),
        lambda: RelationalColumn(cast(Any, 42), "string"),
        lambda: RelationalIndex("unsafe-name", ("email",)),
        lambda: RelationalIndex(cast(Any, 42), ("email",)),
        lambda: RelationalIndex("safe_name", ()),
        lambda: RelationalIndex("safe_name", ("email", "email")),
        lambda: RelationalIndex("safe_name", (cast(Any, 42),)),
    ],
)
def test_column_and_index_declarations_reject_invalid_names_or_columns(
    declaration,
) -> None:
    with pytest.raises(ValueError):
        declaration()


def test_column_declaration_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="Unsupported relational column kind"):
        RelationalColumn("payload", cast(Any, "binary"))


def test_column_declaration_rejects_internal_prefix() -> None:
    with pytest.raises(ValueError, match=r"reserved '_arclith_' prefix"):
        RelationalColumn("_arclith_pagination_total", "integer")


def test_registry_rejects_unsafe_table_name() -> None:
    class UnsafeTableMapper(UserAccountMapper):
        table_name = "unsafe-name"

    with pytest.raises(ValueError, match="table name"):
        RelationalMapperRegistry().register(UnsafeTableMapper())


def test_registry_rejects_unknown_index_column() -> None:
    class UnknownIndexColumnMapper(UserAccountMapper):
        indexes = (RelationalIndex("ix_unknown", ("missing",)),)

    with pytest.raises(ValueError, match=r"unknown columns: missing"):
        RelationalMapperRegistry().register(UnknownIndexColumnMapper())


def test_registry_requires_repository_lifecycle_columns() -> None:
    class IncompleteMapper(UserAccountMapper):
        columns = UserAccountMapper.columns[:-1]

    with pytest.raises(ValueError, match=r"missing Repository columns: version"):
        RelationalMapperRegistry().register(IncompleteMapper())


def test_mapper_protocol_is_satisfied_statically() -> None:
    mapper: RelationalEntityMapper[UserAccount] = UserAccountMapper()

    assert mapper.entity_class is UserAccount


def test_domain_does_not_import_sqlalchemy() -> None:
    imported_modules: set[str] = set()
    domain_path = Path(domain_package.__file__).resolve().parent
    for source_path in domain_path.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.add(node.module)

    assert not any(
        module == "sqlalchemy" or module.startswith("sqlalchemy.")
        for module in imported_modules
    )
