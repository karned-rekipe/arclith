import asyncio
from datetime import date, datetime, timezone
import json
from typing import Any

import pytest
from pydantic import Field

pytest.importorskip("sqlalchemy")

from arclith.adapters.outbound.postgresql.config import PostgreSQLConfig
from arclith.adapters.outbound.postgresql.repository import PostgreSQLRepository
from arclith.domain.models.entity import Entity


class Item(Entity):
    name: str = "item"


class RichItem(Entity):
    name: str
    due_on: date
    metadata: dict[str, Any] = Field(default_factory=dict)


class FakeConnection:
    def __init__(self, engine: "FakeEngine") -> None:
        self._engine = engine

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

    def begin(self) -> FakeBegin:
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
    assert len(repository._schema_locks) == 1


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
