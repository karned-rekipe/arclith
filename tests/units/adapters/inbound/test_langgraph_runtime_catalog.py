from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from arclith.adapters.inbound.langgraph_runtime.catalog import (
    PostgresRuntimeCatalog,
    RunRecord,
    ThreadAlreadyExistsError,
)

THREAD_ID = "01993fb0-7a3d-71a0-9c20-d7abbd755180"
RUN_ID = "01993fb0-7a3d-71a0-9c20-d7abbd755181"
NOW = datetime(2026, 8, 28, tzinfo=UTC)


class FakeCursor:
    def __init__(self, response: Any) -> None:
        self.response = response

    async def fetchone(self) -> Any:
        return self.response

    async def fetchall(self) -> list[Any]:
        return list(self.response or [])


class FakeConnection:
    def __init__(
        self, responses: list[Any], *, failure: Exception | None = None
    ) -> None:
        self.responses = responses
        self.failure = failure
        self.executions: list[tuple[str, Any]] = []

    async def execute(self, statement: str, parameters: Any = None) -> FakeCursor:
        self.executions.append((" ".join(statement.split()), parameters))
        if self.failure is not None:
            raise self.failure
        response = self.responses.pop(0) if self.responses else None
        return FakeCursor(response)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield


class FakePool:
    def __init__(self, *responses: Any, failure: Exception | None = None) -> None:
        self.connection_instance = FakeConnection(list(responses), failure=failure)

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[FakeConnection]:
        yield self.connection_instance


def _thread_row(*, status: str = "idle") -> dict[str, Any]:
    return {
        "thread_id": THREAD_ID,
        "status": status,
        "metadata": {"tenant": "one"},
        "created_at": NOW,
        "updated_at": NOW,
    }


def _run_row(*, status: str = "running", error: Any = None) -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "thread_id": THREAD_ID,
        "assistant_id": "assistant",
        "status": status,
        "input": {"value": 1},
        "output": {"value": 2} if status == "success" else None,
        "error": error,
        "created_at": NOW,
        "updated_at": NOW,
    }


@pytest.mark.asyncio
async def test_postgres_catalog_sets_up_and_reports_health() -> None:
    pool = FakePool(
        None,
        None,
        None,
        {
            "thread_table": "arclith_langgraph_thread",
            "run_table": "arclith_langgraph_run",
            "checkpoint_table": "checkpoints",
            "store_table": "store",
        },
    )
    catalog = PostgresRuntimeCatalog(pool)

    await catalog.setup()
    assert await catalog.healthcheck() is True
    assert len(pool.connection_instance.executions) == 4
    assert (
        "CREATE TABLE IF NOT EXISTS arclith_langgraph_thread"
        in (pool.connection_instance.executions[0][0])
    )

    assert (
        await PostgresRuntimeCatalog(
            FakePool(failure=ConnectionError("database unavailable"))
        ).healthcheck()
        is False
    )
    assert await PostgresRuntimeCatalog(FakePool(None)).healthcheck() is False


@pytest.mark.asyncio
async def test_postgres_catalog_manages_threads_and_filters() -> None:
    pool = FakePool(
        _thread_row(),
        _thread_row(),
        [_thread_row()],
        None,
        None,
        None,
    )
    catalog = PostgresRuntimeCatalog(pool)

    created = await catalog.create_thread(THREAD_ID, {"tenant": "one"})
    fetched = await catalog.get_thread(THREAD_ID)
    searched = await catalog.search_threads(
        metadata={"tenant": "one"},
        status="idle",
        limit=20,
        offset=1,
    )
    await catalog.set_thread_status(THREAD_ID, "busy")
    await catalog.delete_thread(THREAD_ID)

    assert created.thread_id == THREAD_ID
    assert fetched is not None and fetched.metadata == {"tenant": "one"}
    assert searched == [created]
    search_parameters = pool.connection_instance.executions[2][1]
    assert search_parameters == (
        "idle",
        "idle",
        '{"tenant": "one"}',
        '{"tenant": "one"}',
        20,
        1,
    )


@pytest.mark.asyncio
async def test_postgres_catalog_handles_thread_conflicts() -> None:
    catalog = PostgresRuntimeCatalog(FakePool(None))
    with pytest.raises(ThreadAlreadyExistsError):
        await catalog.create_thread(
            THREAD_ID,
            {},
            if_exists="raise",
        )

    existing = await PostgresRuntimeCatalog(
        FakePool(None, _thread_row())
    ).create_thread(THREAD_ID, {}, if_exists="do_nothing")
    assert existing.thread_id == THREAD_ID

    with pytest.raises(RuntimeError, match="did not return"):
        await PostgresRuntimeCatalog(FakePool(None, None)).create_thread(
            THREAD_ID,
            {},
        )


@pytest.mark.asyncio
async def test_postgres_catalog_manages_runs_and_statuses() -> None:
    pool = FakePool(
        _run_row(),
        None,
        _run_row(status="success"),
        None,
        _run_row(status="success"),
        [_run_row(status="success")],
    )
    catalog = PostgresRuntimeCatalog(pool)
    original = RunRecord(
        run_id=RUN_ID,
        thread_id=THREAD_ID,
        assistant_id="assistant",
        status="running",
        input={"value": 1},
    )

    created = await catalog.create_run(original)
    finished = await catalog.finish_run(
        RUN_ID,
        status="success",
        output={"value": 2},
    )
    fetched = await catalog.get_run(THREAD_ID, RUN_ID)
    listed = await catalog.list_runs(
        THREAD_ID,
        status="success",
        limit=10,
        offset=0,
    )

    assert created.status == "running"
    assert finished is not None and finished.output == {"value": 2}
    assert fetched is not None and fetched.as_api_dict()["run_id"] == RUN_ID
    assert listed[0].status == "success"
    assert pool.connection_instance.executions[-1][1] == (
        THREAD_ID,
        "success",
        "success",
        10,
        0,
    )


@pytest.mark.asyncio
async def test_postgres_catalog_handles_missing_runs_and_unfiltered_lists() -> None:
    missing_create = PostgresRuntimeCatalog(FakePool(None))
    with pytest.raises(RuntimeError, match="Run creation"):
        await missing_create.create_run(
            RunRecord(
                run_id=RUN_ID,
                thread_id=THREAD_ID,
                assistant_id="assistant",
                status="running",
            )
        )

    catalog = PostgresRuntimeCatalog(FakePool(None, None, []))
    assert await catalog.finish_run(RUN_ID, status="error") is None
    assert await catalog.get_run(THREAD_ID, RUN_ID) is None
    assert (
        await catalog.list_runs(
            THREAD_ID,
            status=None,
            limit=10,
            offset=0,
        )
        == []
    )
