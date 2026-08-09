from pathlib import Path

from arclith import Arclith
from arclith.adapters.outbound.memory.cache_adapter import MemoryCacheAdapter


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
