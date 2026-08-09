from types import SimpleNamespace

import pytest

from arclith.adapters.context import _tenant_context, get_adapter_tenant_context
from arclith.adapters.inbound.fastapi.dependencies import make_inject_tenant_uri
from arclith.domain.models.tenant import AdapterTenantCoords, TenantContext
from arclith.domain.ports.outbound.tenant_resolver import TenantResolver
from arclith.infrastructure.config import AppConfig, AdaptersSettings, MongoDBSettings, TenantSettings


class FakeJWTDecoder:
    def __init__(self, claims: dict[str, str]) -> None:
        self.claims = claims
        self.token: str | None = None

    async def decode(self, token: str) -> dict[str, str]:
        self.token = token
        return self.claims


class FakeTenantResolver(TenantResolver):
    def __init__(self, adapter_name: str, params: dict[str, str]) -> None:
        self.adapter_name = adapter_name
        self.params = params
        self.tenant_id: str | None = None

    async def resolve(self, tenant_id: str) -> TenantContext:
        self.tenant_id = tenant_id
        return TenantContext(
            adapters={self.adapter_name: AdapterTenantCoords(params=self.params)}
        )


@pytest.mark.asyncio
async def test_fastapi_tenant_pipeline_bypasses_single_tenant_without_decoder() -> None:
    config = AppConfig(
        adapters=AdaptersSettings(
            repository="mongodb",
            mongodb=MongoDBSettings(db_name="test", multitenant=False),
        )
    )
    dependency = make_inject_tenant_uri(config)

    await dependency(SimpleNamespace(headers={}))


@pytest.mark.asyncio
async def test_fastapi_tenant_pipeline_uses_configured_claim_and_generic_resolvers() -> None:
    config = AppConfig(
        adapters=AdaptersSettings(
            repository="mongodb",
            mongodb=MongoDBSettings(db_name="fallback", multitenant=True),
        ),
        tenant=TenantSettings(
            vault_addr="http://vault:8200",
            vault_mount="kv",
            vault_path_prefix="rekipe/tenants",
            tenant_claim="tenant_id",
        ),
    )
    decoder = FakeJWTDecoder({"tenant_id": "tenant-a"})
    mongodb = FakeTenantResolver("mongodb", {"uri": "mongodb://tenant-a", "db_name": "tenant_a"})
    s3 = FakeTenantResolver("s3", {"bucket_name": "tenant-a-assets"})
    dependency = make_inject_tenant_uri(
        config,
        jwt_decoder=decoder,  # type: ignore[arg-type]
        tenant_resolvers=[mongodb, s3],
    )
    token = _tenant_context.set(None)
    try:
        await dependency(SimpleNamespace(headers={"Authorization": "Bearer jwt-token"}))

        mongodb_context = get_adapter_tenant_context("mongodb")
        s3_context = get_adapter_tenant_context("s3")
    finally:
        _tenant_context.reset(token)

    assert decoder.token == "jwt-token"
    assert mongodb.tenant_id == "tenant-a"
    assert s3.tenant_id == "tenant-a"
    assert mongodb_context is not None
    assert mongodb_context.params == {"uri": "mongodb://tenant-a", "db_name": "tenant_a"}
    assert s3_context is not None
    assert s3_context.params == {"bucket_name": "tenant-a-assets"}
