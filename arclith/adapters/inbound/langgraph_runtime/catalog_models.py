from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol


class ThreadAlreadyExistsError(RuntimeError):
    pass


@dataclass(frozen=True)
class ThreadRecord:
    thread_id: str
    status: str = "idle"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_api_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
            "status": self.status,
            "config": {"configurable": {"thread_id": self.thread_id}},
            "values": None,
            "interrupts": {},
        }


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    thread_id: str
    assistant_id: str
    status: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    input: Any = None
    output: Any = None
    error: dict[str, Any] | None = None

    def as_api_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "thread_id": self.thread_id,
            "assistant_id": self.assistant_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "status": self.status,
            "metadata": {},
        }


class RuntimeCatalog(Protocol):
    async def setup(self) -> None:
        raise NotImplementedError  # pragma: no cover - protocol contract

    async def healthcheck(self) -> bool:
        raise NotImplementedError  # pragma: no cover - protocol contract

    async def create_thread(
        self,
        thread_id: str,
        metadata: dict[str, Any],
        *,
        if_exists: str | None = None,
    ) -> ThreadRecord:
        raise NotImplementedError  # pragma: no cover - protocol contract

    async def get_thread(self, thread_id: str) -> ThreadRecord | None:
        raise NotImplementedError  # pragma: no cover - protocol contract

    async def search_threads(
        self,
        *,
        metadata: dict[str, Any] | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[ThreadRecord]:
        raise NotImplementedError  # pragma: no cover - protocol contract

    async def set_thread_status(self, thread_id: str, status: str) -> None:
        raise NotImplementedError  # pragma: no cover - protocol contract

    async def delete_thread(self, thread_id: str) -> None:
        raise NotImplementedError  # pragma: no cover - protocol contract

    async def create_run(self, record: RunRecord) -> RunRecord:
        raise NotImplementedError  # pragma: no cover - protocol contract

    async def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        output: Any = None,
        error: dict[str, Any] | None = None,
    ) -> RunRecord | None:
        raise NotImplementedError  # pragma: no cover - protocol contract

    async def get_run(self, thread_id: str, run_id: str) -> RunRecord | None:
        raise NotImplementedError  # pragma: no cover - protocol contract

    async def list_runs(
        self,
        thread_id: str,
        *,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[RunRecord]:
        raise NotImplementedError  # pragma: no cover - protocol contract
