from arclith.domain.ports.outbound.cache import CachePort


class RedisCacheAdapter(CachePort):
    def __init__(self, url: str) -> None:
        try:
            from redis.asyncio import Redis  # type: ignore[import-untyped]
        except ModuleNotFoundError as exc:
            if exc.name != "redis":
                raise
            raise ModuleNotFoundError("Package redis manquant : uv add 'arclith[cache]'") from None
        self._client = Redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        return await self._client.get(key)

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        await self._client.setex(key, ttl_s, value)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)
