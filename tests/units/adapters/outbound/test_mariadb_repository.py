import asyncio

from arclith.adapters.outbound.mariadb.config import MariaDBConfig
from arclith.adapters.outbound.mariadb.repository import MariaDBRepository
from arclith.domain.models.entity import Entity


class Item(Entity):
    name: str = "item"


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


async def test_ensure_schema_is_locked_per_url(logger) -> None:
    repository = MariaDBRepository(MariaDBConfig(database="demo"), Item, logger)
    engine = FakeEngine()

    await asyncio.gather(*(repository._ensure_schema(engine, "mysql://demo") for _ in range(5)))

    assert engine.begin_calls == 1
    assert engine.run_sync_calls == 1
