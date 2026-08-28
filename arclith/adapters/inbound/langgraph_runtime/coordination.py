from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol


class RunBusyError(RuntimeError):
    pass


class RunCoordinator(Protocol):
    def thread_lock(self, thread_id: str, *, timeout_seconds: int) -> Any: ...

    async def request_cancel(self, run_id: str) -> None: ...

    async def is_cancelled(self, run_id: str) -> bool: ...

    async def clear_cancel(self, run_id: str) -> None: ...

    async def healthcheck(self) -> bool: ...

    async def close(self) -> None: ...


class InMemoryRunCoordinator:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._cancelled: set[str] = set()

    @asynccontextmanager
    async def thread_lock(
        self, thread_id: str, *, timeout_seconds: int
    ) -> AsyncIterator[None]:
        del timeout_seconds
        lock = self._locks.setdefault(thread_id, asyncio.Lock())
        if lock.locked():
            raise RunBusyError(f"Thread {thread_id} already has an active run")
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()

    async def request_cancel(self, run_id: str) -> None:
        self._cancelled.add(run_id)

    async def is_cancelled(self, run_id: str) -> bool:
        return run_id in self._cancelled

    async def clear_cancel(self, run_id: str) -> None:
        self._cancelled.discard(run_id)

    async def close(self) -> None:
        return None

    async def healthcheck(self) -> bool:
        return True


class RedisRunCoordinator:
    def __init__(
        self,
        client: Any,
        *,
        prefix: str = "arclith:langgraph",
        lease_seconds: float = 30,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds doit etre strictement positif")
        self._client = client
        self._prefix = prefix.strip(":")
        self._lease_seconds = lease_seconds

    @asynccontextmanager
    async def thread_lock(
        self, thread_id: str, *, timeout_seconds: int
    ) -> AsyncIterator[None]:
        del timeout_seconds
        lock = self._client.lock(
            f"{self._prefix}:thread:{thread_id}:lock",
            timeout=self._lease_seconds,
            blocking_timeout=0,
        )
        if not await lock.acquire(blocking=False):
            raise RunBusyError(f"Thread {thread_id} already has an active run")
        owner = asyncio.current_task()
        renewal = asyncio.create_task(self._renew_lock(lock, owner))
        try:
            yield
        finally:
            renewal.cancel()
            try:
                await renewal
            except asyncio.CancelledError:
                pass
            try:
                await lock.release()
            except Exception as error:  # pragma: no cover - defensive Redis race
                if error.__class__.__name__ != "LockNotOwnedError":
                    raise

    async def _renew_lock(self, lock: Any, owner: asyncio.Task[Any] | None) -> None:
        while True:
            await asyncio.sleep(self._lease_seconds / 3)
            try:
                extended = await lock.extend(
                    self._lease_seconds,
                    replace_ttl=True,
                )
            except Exception:
                extended = False
            if not extended:
                if owner is not None:
                    owner.cancel()
                return

    async def request_cancel(self, run_id: str) -> None:
        await self._client.set(
            f"{self._prefix}:run:{run_id}:cancelled",
            "1",
            ex=3600,
        )

    async def is_cancelled(self, run_id: str) -> bool:
        value = await self._client.get(f"{self._prefix}:run:{run_id}:cancelled")
        return value is not None

    async def clear_cancel(self, run_id: str) -> None:
        await self._client.delete(f"{self._prefix}:run:{run_id}:cancelled")

    async def healthcheck(self) -> bool:
        try:
            return bool(await self._client.ping())
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()
