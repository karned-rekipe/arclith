import asyncio
from collections.abc import Mapping
from datetime import date, datetime, timezone
import json
from typing import Any

import pytest
from pydantic import Field

pytest.importorskip("sqlalchemy")

from arclith.adapters.outbound.postgresql.config import PostgreSQLConfig
from arclith.adapters.outbound.postgresql.repository import PostgreSQLRepository
from arclith.adapters.outbound.relational import RelationalColumn, RelationalIndex
from arclith.domain.models.entity import Entity


class Item(Entity):
    name: str = "item"


class RichItem(Entity):
    name: str
    due_on: date
    metadata: dict[str, Any] = Field(default_factory=dict)


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


class FakeResult:
    def __init__(self, *, first: Any = None, rows: list[Any] | None = None) -> None:
        self._first = first
        self._rows = rows or []

    def mappings(self) -> "FakeResult":
        return self

    def first(self) -> Any:
        return self._first

    def all(self) -> list[Any]:
        return self._rows


class FakeConnection:
    def __init__(self, engine: "FakeEngine") -> None:
        self._engine = engine

    async def execute(self, statement) -> FakeResult:
        self._engine.executed_statements.append(statement)
        await asyncio.sleep(0)
        if self._engine.results:
            return self._engine.results.pop(0)
        return FakeResult()

    async def run_sync(self, fn) -> None:
        self._engine.run_sync_calls += 1
        await asyncio.sleep(0)


class FakeBegin:
    def __init__(self, engine: "FakeEngine") -> None:
        self._engine = engine

    async def __aenter__(self) -> FakeConnection:
        self._engine.begin_calls += 1
        await asyncio.sleep(0)
        return FakeConnection(self._engine)

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class FakeEngine:
    def __init__(self) -> None:
        self.begin_calls = 0
        self.run_sync_calls = 0
        self.executed_statements: list[Any] = []
        self.results: list[FakeResult] = []

    def begin(self) -> FakeBegin:
        return FakeBegin(self)

    def connect(self) -> FakeBegin:
        return FakeBegin(self)


def test_build_table_uses_schema_prefix_and_jsonb(logger) -> None:
    repository = PostgreSQLRepository(
        PostgreSQLConfig(database="demo", schema="app", table_prefix="svc_"),
        Item,
        logger,
    )

    _metadata, table = repository._table_for(repository._config)

    assert table.schema == "app"
    assert table.name == "svc_item"
    assert table.c.uuid.type.length == 36
    assert table.c.data.type.__class__.__name__ == "JSONB"


def test_build_structured_table_transmits_columns_constraints_and_indexes(
    logger,
) -> None:
    repository = PostgreSQLRepository(
        PostgreSQLConfig(
            database="demo",
            schema="app",
            table_prefix="svc_",
            mapping_strategy="structured",
        ),
        UserAccount,
        logger,
        mapper=UserAccountMapper(),
    )

    _metadata, table = repository._table_for(repository._config)

    assert table.schema == "app"
    assert table.name == "svc_user_accounts"
    assert table.c.uuid.primary_key is True
    assert table.c.uuid.type.__class__.__name__ == "Uuid"
    assert table.c.email.unique is True
    assert table.c.email.index is True
    explicit_index = next(
        index
        for index in table.indexes
        if index.name == "ix_user_accounts_display_created"
    )
    assert [column.name for column in explicit_index.columns] == [
        "display_name",
        "created_at",
    ]


async def test_structured_crud_uses_mapper_without_implicit_schema_creation(
    logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = UserAccount(email="ada@example.net", display_name="Ada")
    mapper = UserAccountMapper()
    repository = PostgreSQLRepository(
        PostgreSQLConfig(
            database="demo",
            mapping_strategy="structured",
            auto_create_schema=False,
        ),
        UserAccount,
        logger,
        mapper=mapper,
    )
    engine = FakeEngine()
    engine.results = [
        FakeResult(),
        FakeResult(first=dict(mapper.to_record(account))),
        FakeResult(),
        FakeResult(),
    ]
    monkeypatch.setattr(repository, "_engine_for", lambda *args: engine)

    assert await repository.create(account) == account
    assert await repository.read(account.uuid) == account
    assert await repository.update(account) == account
    await repository.delete(account.uuid)

    assert engine.run_sync_calls == 0
    assert [statement.__class__.__name__ for statement in engine.executed_statements] == [
        "Insert",
        "Select",
        "Update",
        "Delete",
    ]


def test_structured_record_must_match_declared_columns(logger) -> None:
    class IncompleteMapper(UserAccountMapper):
        def to_record(self, entity: UserAccount) -> Mapping[str, Any]:
            record = dict(super().to_record(entity))
            record.pop("version")
            return record

    account = UserAccount(email="ada@example.net", display_name="Ada")
    repository = PostgreSQLRepository(
        PostgreSQLConfig(database="demo", mapping_strategy="structured"),
        UserAccount,
        logger,
        mapper=IncompleteMapper(),
    )

    with pytest.raises(ValueError, match=r"missing: version"):
        repository._entity_values(account)


async def test_ensure_schema_is_locked_per_url(logger) -> None:
    repository = PostgreSQLRepository(PostgreSQLConfig(database="demo"), Item, logger)
    engine = FakeEngine()
    metadata, _table = repository._table_for(repository._config)

    await asyncio.gather(
        *(
            repository._ensure_schema(
                engine, "postgresql://demo", metadata, "public.item"
            )
            for _ in range(5)
        )
    )

    assert engine.begin_calls == 1
    assert engine.run_sync_calls == 1
    assert engine.executed_statements == []
    assert len(repository._schema_locks) == 1


async def test_ensure_schema_creates_custom_schema_before_tables(logger) -> None:
    repository = PostgreSQLRepository(
        PostgreSQLConfig(database="demo", schema="tenant_a"),
        Item,
        logger,
    )
    engine = FakeEngine()
    metadata, _table = repository._table_for(repository._config)

    await repository._ensure_schema(
        engine, "postgresql://demo", metadata, "tenant_a.item"
    )

    assert engine.begin_calls == 1
    assert engine.run_sync_calls == 1
    assert len(engine.executed_statements) == 1
    statement = engine.executed_statements[0]
    assert statement.element == "tenant_a"
    assert statement.if_not_exists is True


def test_entity_serialization_round_trip_preserves_pydantic_values(logger) -> None:
    now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    entity = RichItem(
        name="deadline",
        due_on=date(2026, 9, 1),
        metadata={"nested": {"rank": 1}},
        created_at=now,
        updated_at=now,
    )
    repository = PostgreSQLRepository(
        PostgreSQLConfig(database="demo"), RichItem, logger
    )

    values = repository._entity_values(entity)
    restored = repository._row_to_entity({"data": values["data"]})

    assert values["data"]["uuid"] == str(entity.uuid)
    assert values["data"]["created_at"] == "2026-08-25T12:00:00Z"
    assert values["data"]["due_on"] == "2026-09-01"
    assert restored == entity


def test_row_to_entity_accepts_serialized_json_string(logger) -> None:
    entity = Item(name="json")
    repository = PostgreSQLRepository(PostgreSQLConfig(database="demo"), Item, logger)

    restored = repository._row_to_entity(
        {"data": json.dumps(entity.model_dump(mode="json"))}
    )

    assert restored == entity
