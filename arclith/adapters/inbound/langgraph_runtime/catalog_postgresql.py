from __future__ import annotations

import json
from typing import Any

from arclith.adapters.inbound.langgraph_runtime.catalog_models import (
    RunRecord,
    ThreadAlreadyExistsError,
    ThreadRecord,
)


class PostgresRuntimeCatalog:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS arclith_langgraph_thread (
                    thread_id UUID PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'idle',
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS arclith_langgraph_run (
                    run_id UUID PRIMARY KEY,
                    thread_id UUID NOT NULL REFERENCES arclith_langgraph_thread(thread_id)
                        ON DELETE CASCADE,
                    assistant_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input JSONB,
                    output JSONB,
                    error JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            await connection.execute(
                """
                CREATE INDEX IF NOT EXISTS arclith_langgraph_run_thread_created_idx
                ON arclith_langgraph_run (thread_id, created_at DESC)
                """
            )

    async def healthcheck(self) -> bool:
        try:
            async with self._pool.connection() as connection:
                cursor = await connection.execute(
                    """
                    SELECT
                        to_regclass('arclith_langgraph_thread') AS thread_table,
                        to_regclass('arclith_langgraph_run') AS run_table,
                        to_regclass('checkpoints') AS checkpoint_table,
                        to_regclass('store') AS store_table
                    """
                )
                row = await cursor.fetchone()
        except Exception:
            return False
        return row is not None and all(row.values())

    async def create_thread(
        self,
        thread_id: str,
        metadata: dict[str, Any],
        *,
        if_exists: str | None = None,
    ) -> ThreadRecord:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO arclith_langgraph_thread (thread_id, metadata)
                VALUES (%s, %s::jsonb)
                ON CONFLICT (thread_id) DO NOTHING
                RETURNING thread_id, status, metadata, created_at, updated_at
                """,
                (thread_id, json.dumps(metadata)),
            )
            row = await cursor.fetchone()
        if row is None:
            if if_exists == "raise":
                raise ThreadAlreadyExistsError(f"Thread {thread_id} already exists")
            existing = await self.get_thread(thread_id)
            if existing is None:
                raise RuntimeError("Thread creation did not return a record")
            return existing
        return _thread_from_row(row)

    async def get_thread(self, thread_id: str) -> ThreadRecord | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT thread_id, status, metadata, created_at, updated_at
                FROM arclith_langgraph_thread
                WHERE thread_id = %s
                """,
                (thread_id,),
            )
            row = await cursor.fetchone()
        return _thread_from_row(row) if row is not None else None

    async def search_threads(
        self,
        *,
        metadata: dict[str, Any] | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[ThreadRecord]:
        encoded_metadata = json.dumps(metadata) if metadata else None
        parameters = (
            status,
            status,
            encoded_metadata,
            encoded_metadata,
            limit,
            offset,
        )
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT thread_id, status, metadata, created_at, updated_at
                FROM arclith_langgraph_thread
                WHERE (%s::text IS NULL OR status = %s)
                  AND (%s::jsonb IS NULL OR metadata @> %s::jsonb)
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                parameters,
            )
            rows = await cursor.fetchall()
        return [_thread_from_row(row) for row in rows]

    async def set_thread_status(self, thread_id: str, status: str) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                UPDATE arclith_langgraph_thread
                SET status = %s, updated_at = now()
                WHERE thread_id = %s
                """,
                (status, thread_id),
            )

    async def delete_thread(self, thread_id: str) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                "DELETE FROM arclith_langgraph_thread WHERE thread_id = %s",
                (thread_id,),
            )

    async def create_run(self, record: RunRecord) -> RunRecord:
        async with (
            self._pool.connection() as connection,
            connection.transaction(),
        ):
            cursor = await connection.execute(
                """
                    INSERT INTO arclith_langgraph_run (
                        run_id, thread_id, assistant_id, status, input
                    ) VALUES (%s, %s, %s, %s, %s::jsonb)
                    RETURNING run_id, thread_id, assistant_id, status, input, output,
                              error, created_at, updated_at
                    """,
                (
                    record.run_id,
                    record.thread_id,
                    record.assistant_id,
                    record.status,
                    json.dumps(record.input),
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("Run creation did not return a record")
            await connection.execute(
                """
                    UPDATE arclith_langgraph_thread
                    SET status = 'busy', updated_at = now()
                    WHERE thread_id = %s
                    """,
                (record.thread_id,),
            )
        return _run_from_row(row)

    async def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        output: Any = None,
        error: dict[str, Any] | None = None,
    ) -> RunRecord | None:
        async with (
            self._pool.connection() as connection,
            connection.transaction(),
        ):
            cursor = await connection.execute(
                """
                    UPDATE arclith_langgraph_run
                    SET status = %s, output = %s::jsonb, error = %s::jsonb,
                        updated_at = now()
                    WHERE run_id = %s
                    RETURNING run_id, thread_id, assistant_id, status, input, output,
                              error, created_at, updated_at
                    """,
                (status, json.dumps(output), json.dumps(error), run_id),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            record = _run_from_row(row)
            thread_status = "idle" if status == "success" else status
            await connection.execute(
                """
                    UPDATE arclith_langgraph_thread
                    SET status = %s, updated_at = now()
                    WHERE thread_id = %s
                    """,
                (thread_status, record.thread_id),
            )
        return record

    async def get_run(self, thread_id: str, run_id: str) -> RunRecord | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT run_id, thread_id, assistant_id, status, input, output,
                       error, created_at, updated_at
                FROM arclith_langgraph_run
                WHERE thread_id = %s AND run_id = %s
                """,
                (thread_id, run_id),
            )
            row = await cursor.fetchone()
        return _run_from_row(row) if row is not None else None

    async def list_runs(
        self,
        thread_id: str,
        *,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[RunRecord]:
        parameters = (thread_id, status, status, limit, offset)
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT run_id, thread_id, assistant_id, status, input, output,
                       error, created_at, updated_at
                FROM arclith_langgraph_run
                WHERE thread_id = %s
                  AND (%s::text IS NULL OR status = %s)
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                parameters,
            )
            rows = await cursor.fetchall()
        return [_run_from_row(row) for row in rows]


def _thread_from_row(row: Any) -> ThreadRecord:
    return ThreadRecord(
        thread_id=str(row["thread_id"]),
        status=str(row["status"]),
        metadata=dict(row["metadata"] or {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _run_from_row(row: Any) -> RunRecord:
    return RunRecord(
        run_id=str(row["run_id"]),
        thread_id=str(row["thread_id"]),
        assistant_id=str(row["assistant_id"]),
        status=str(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        input=row["input"],
        output=row["output"],
        error=dict(row["error"]) if row["error"] else None,
    )
