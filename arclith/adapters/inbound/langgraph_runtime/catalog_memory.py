from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from arclith.adapters.inbound.langgraph_runtime.catalog_models import (
    RunRecord,
    ThreadAlreadyExistsError,
    ThreadRecord,
)


class InMemoryRuntimeCatalog:
    def __init__(self) -> None:
        self._threads: dict[str, ThreadRecord] = {}
        self._runs: dict[str, RunRecord] = {}

    async def setup(self) -> None:
        return None

    async def healthcheck(self) -> bool:
        return True

    async def create_thread(
        self,
        thread_id: str,
        metadata: dict[str, Any],
        *,
        if_exists: str | None = None,
    ) -> ThreadRecord:
        existing = self._threads.get(thread_id)
        if existing is not None:
            if if_exists == "raise":
                raise ThreadAlreadyExistsError(f"Thread {thread_id} already exists")
            return existing
        record = ThreadRecord(thread_id=thread_id, metadata=dict(metadata))
        self._threads[thread_id] = record
        return record

    async def get_thread(self, thread_id: str) -> ThreadRecord | None:
        return self._threads.get(thread_id)

    async def search_threads(
        self,
        *,
        metadata: dict[str, Any] | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[ThreadRecord]:
        records = sorted(
            self._threads.values(), key=lambda item: item.created_at, reverse=True
        )
        if status is not None:
            records = [record for record in records if record.status == status]
        if metadata:
            records = [
                record
                for record in records
                if all(
                    record.metadata.get(key) == value for key, value in metadata.items()
                )
            ]
        return records[offset : offset + limit]

    async def set_thread_status(self, thread_id: str, status: str) -> None:
        record = self._threads.get(thread_id)
        if record is None:
            return
        self._threads[thread_id] = ThreadRecord(
            thread_id=record.thread_id,
            status=status,
            metadata=record.metadata,
            created_at=record.created_at,
            updated_at=datetime.now(UTC),
        )

    async def delete_thread(self, thread_id: str) -> None:
        self._threads.pop(thread_id, None)
        self._runs = {
            run_id: run
            for run_id, run in self._runs.items()
            if run.thread_id != thread_id
        }

    async def create_run(self, record: RunRecord) -> RunRecord:
        self._runs[record.run_id] = record
        await self.set_thread_status(record.thread_id, "busy")
        return record

    async def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        output: Any = None,
        error: dict[str, Any] | None = None,
    ) -> RunRecord | None:
        record = self._runs.get(run_id)
        if record is None:
            return None
        updated = RunRecord(
            run_id=record.run_id,
            thread_id=record.thread_id,
            assistant_id=record.assistant_id,
            status=status,
            created_at=record.created_at,
            updated_at=datetime.now(UTC),
            input=record.input,
            output=output,
            error=error,
        )
        self._runs[run_id] = updated
        thread_status = "idle" if status == "success" else status
        await self.set_thread_status(record.thread_id, thread_status)
        return updated

    async def get_run(self, thread_id: str, run_id: str) -> RunRecord | None:
        record = self._runs.get(run_id)
        if record is None or record.thread_id != thread_id:
            return None
        return record

    async def list_runs(
        self,
        thread_id: str,
        *,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[RunRecord]:
        records = sorted(
            (run for run in self._runs.values() if run.thread_id == thread_id),
            key=lambda item: item.created_at,
            reverse=True,
        )
        if status is not None:
            records = [record for record in records if record.status == status]
        return records[offset : offset + limit]
