from __future__ import annotations

import asyncio
import json

from arclith.domain.models.tenant import AdapterTenantCoords, TenantContext
from arclith.domain.ports.outbound.cache import CachePort
from arclith.domain.ports.outbound.tenant_resolver import TenantResolver


class VaultTenantResolver(TenantResolver):
    """Résout le TenantContext depuis un secret Vault KV v2.

    Tous les champs du secret sont exposés tels quels dans ``AdapterTenantCoords.params``.
    L'adaptateur consommateur lit ce dont il a besoin via ``coords.get(key)`` / ``coords.require(key)``.

    Structure Vault attendue (exemple MongoDB) :
        vault kv put kv/rekipe/tenants/tenant-abc \\
            uri="mongodb://..." db_name="tenant_abc"

    Structure Vault pour S3 :
        vault kv put kv/rekipe/tenants/tenant-abc \\
            endpoint_url="https://..." bucket_name="tenant-abc" region="eu-west-1"
    """

    def __init__(
        self,
        adapter_name: str,
        addr: str,
        mount: str,
        path_prefix: str,
        cache: CachePort,
        ttl_s: int = 300,
    ) -> None:
        self._adapter_name = adapter_name
        self._addr = addr
        self._mount = mount
        self._path_prefix = path_prefix
        self._cache = cache
        self._ttl_s = ttl_s

    async def resolve(self, tenant_id: str) -> TenantContext:
        key = f"tenant:{self._adapter_name}:{tenant_id}"
        cached = await self._cache.get(key)
        if cached:
            params = json.loads(cached)
        else:
            params = await asyncio.get_event_loop().run_in_executor(None, self._fetch, tenant_id)
            await self._cache.set(key, json.dumps(params), self._ttl_s)

        return TenantContext(adapters={
            self._adapter_name: AdapterTenantCoords(params={k: str(v) for k, v in params.items()})
        })

    def _fetch(self, tenant_id: str) -> dict:
        import hvac  # type: ignore[import-untyped]
        from arclith.adapters.outbound.vault.secret_adapter import _read_vault_token

        token = _read_vault_token()
        client = hvac.Client(url=self._addr, token=token)
        response = client.secrets.kv.v2.read_secret_version(
            path=f"{self._path_prefix}/{tenant_id}",
            mount_point=self._mount,
            raise_on_deleted_version=True,
        )
        return response["data"]["data"]
