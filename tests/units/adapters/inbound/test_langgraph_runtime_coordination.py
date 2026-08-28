from __future__ import annotations

import asyncio
from typing import Any

import pytest

from arclith.adapters.inbound.langgraph_runtime.coordination import (
    RedisRunCoordinator,
    RunBusyError,
)


class FakeLock:
    def __init__(self, acquired: bool, *, extendable: bool = True) -> None:
        self.acquired = acquired
        self.extendable = extendable
        self.released = False
        self.extended = 0

    async def acquire(self, *, blocking: bool) -> bool:
        assert blocking is False
        return self.acquired

    async def release(self) -> None:
        self.released = True

    async def extend(self, _seconds: float, *, replace_ttl: bool) -> bool:
        assert replace_ttl is True
        self.extended += 1
        return self.extendable


class FakeRedis:
    def __init__(
        self,
        *,
        acquired: bool = True,
        healthy: bool = True,
        extendable: bool = True,
    ) -> None:
        self.acquired = acquired
        self.healthy = healthy
        self.extendable = extendable
        self.values: dict[str, str] = {}
        self.closed = False
        self.last_lock: FakeLock | None = None

    def lock(self, _name: str, **options: Any) -> FakeLock:
        assert options["blocking_timeout"] == 0
        self.last_lock = FakeLock(self.acquired, extendable=self.extendable)
        return self.last_lock

    async def set(self, key: str, value: str, *, ex: int) -> None:
        assert ex == 3600
        self.values[key] = value

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def ping(self) -> bool:
        return self.healthy

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_redis_coordinator_locks_cancels_and_closes() -> None:
    client = FakeRedis()
    coordinator = RedisRunCoordinator(client, prefix="demo", lease_seconds=0.03)

    async with coordinator.thread_lock("thread", timeout_seconds=42):
        assert client.last_lock is not None
        assert client.last_lock.released is False
        await asyncio.sleep(0.02)
    assert client.last_lock.released is True
    assert client.last_lock.extended >= 1

    await coordinator.request_cancel("run")
    assert await coordinator.is_cancelled("run") is True
    await coordinator.clear_cancel("run")
    assert await coordinator.is_cancelled("run") is False
    assert await coordinator.healthcheck() is True
    await coordinator.close()
    assert client.closed is True


@pytest.mark.asyncio
async def test_redis_coordinator_rejects_busy_thread() -> None:
    coordinator = RedisRunCoordinator(FakeRedis(acquired=False))

    with pytest.raises(RunBusyError):
        async with coordinator.thread_lock("thread", timeout_seconds=42):
            pass


def test_redis_coordinator_rejects_invalid_lease() -> None:
    with pytest.raises(ValueError, match="lease_seconds"):
        RedisRunCoordinator(FakeRedis(), lease_seconds=0)


@pytest.mark.asyncio
async def test_redis_coordinator_cancels_owner_when_lease_is_lost() -> None:
    coordinator = RedisRunCoordinator(
        FakeRedis(extendable=False),
        lease_seconds=0.03,
    )

    async def hold_lock() -> None:
        async with coordinator.thread_lock("thread", timeout_seconds=42):
            await asyncio.sleep(1)

    task = asyncio.create_task(hold_lock())
    with pytest.raises(asyncio.CancelledError):
        await task
