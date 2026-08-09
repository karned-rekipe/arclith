import builtins
from pathlib import Path
from types import SimpleNamespace

import pytest

from arclith import Arclith
from arclith.adapters.outbound.memory.cache_adapter import MemoryCacheAdapter
from arclith.adapters.outbound.redis.cache_adapter import RedisCacheAdapter


def test_arclith_cache_uses_memory_backend(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    cache_dir = config_dir / "adapters" / "inbound"
    cache_dir.mkdir(parents=True)
    (cache_dir / "cache.yaml").write_text(
        "backend: memory\n"
        "jwks_ttl: 1200\n"
        "tenant_uri_ttl: 180\n",
        encoding="utf-8",
    )

    arclith = Arclith(config_dir)

    assert arclith.config.cache.backend == "memory"
    assert arclith.config.cache.jwks_ttl == 1200
    assert arclith.config.cache.tenant_uri_ttl == 180
    assert isinstance(arclith._cache, MemoryCacheAdapter)


def test_arclith_cache_uses_redis_backend_without_real_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "config"
    cache_dir = config_dir / "adapters" / "inbound"
    cache_dir.mkdir(parents=True)
    (cache_dir / "cache.yaml").write_text(
        "backend: redis\n"
        "redis_url: redis://cache:6379/0\n"
        "jwks_ttl: 900\n"
        "tenant_uri_ttl: 120\n",
        encoding="utf-8",
    )

    class FakeRedis:
        url: str | None = None
        decode_responses: bool | None = None

        @classmethod
        def from_url(cls, url: str, *, decode_responses: bool) -> object:
            cls.url = url
            cls.decode_responses = decode_responses
            return object()

    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals: dict | None = None,
        locals: dict | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "redis.asyncio":
            return SimpleNamespace(Redis=FakeRedis)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    arclith = Arclith(config_dir)

    assert arclith.config.cache.backend == "redis"
    assert isinstance(arclith._cache, RedisCacheAdapter)
    assert FakeRedis.url == "redis://cache:6379/0"
    assert FakeRedis.decode_responses is True


def test_redis_cache_adapter_missing_extra_has_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals: dict | None = None,
        locals: dict | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "redis.asyncio":
            raise ModuleNotFoundError("No module named 'redis'", name="redis")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ModuleNotFoundError, match=r"arclith\[cache\]"):
        RedisCacheAdapter("redis://cache:6379/0")
