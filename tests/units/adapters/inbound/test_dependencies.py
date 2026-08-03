import pytest

from arclith.adapters.context import _tenant_context, get_tenant_uri
from arclith.adapters.inbound.dependencies import MissingTenantURIError, apply_tenant_uri
from arclith.infrastructure.config import AppConfig, AdaptersSettings, MongoDBSettings


@pytest.fixture
def single_tenant_config():
    return AppConfig(adapters=AdaptersSettings(
        repository="mongodb",
        mongodb=MongoDBSettings(db_name="test", multitenant=False),
    ))


@pytest.fixture
def multi_tenant_config():
    return AppConfig(adapters=AdaptersSettings(
        repository="mongodb",
        mongodb=MongoDBSettings(db_name="test", multitenant=True),
    ))


async def test_single_tenant_is_noop(single_tenant_config):
    await apply_tenant_uri(single_tenant_config, None)
    assert get_tenant_uri() is None


async def test_single_tenant_ignores_uri(single_tenant_config):
    await apply_tenant_uri(single_tenant_config, "mongodb://ignored")
    assert get_tenant_uri() is None


async def test_multitenant_sets_uri(multi_tenant_config):
    token = _tenant_context.set(None)
    try:
        await apply_tenant_uri(multi_tenant_config, "mongodb://tenant-a")
        assert get_tenant_uri() == "mongodb://tenant-a"
    finally:
        _tenant_context.reset(token)


async def test_multitenant_missing_uri_raises(multi_tenant_config):
    with pytest.raises(MissingTenantURIError):
        await apply_tenant_uri(multi_tenant_config, None)


async def test_multitenant_empty_uri_raises(multi_tenant_config):
    with pytest.raises(MissingTenantURIError):
        await apply_tenant_uri(multi_tenant_config, "")
