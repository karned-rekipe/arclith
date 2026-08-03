from abc import ABC, abstractmethod


class CachePort(ABC):
    @abstractmethod
    async def get(self, key: str) -> str | None: ...

    @abstractmethod
    async def set(self, key: str, value: str, ttl_s: int) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

