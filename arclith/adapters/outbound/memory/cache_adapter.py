import time

from arclith.domain.ports.outbound.cache import CachePort


class MemoryCacheAdapter(CachePort):
    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float]] = {}  # key → (value, expires_at)

    async def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() >= expires_at:
            del self._store[key]
            return None
        return value

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        self._store[key] = (value, time.monotonic() + ttl_s)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

