from datetime import datetime, timedelta, timezone

import pytest
from uuid6 import uuid7

from arclith.application.services.base_service import BaseService
from arclith.adapters.outbound.memory.repository import InMemoryRepository
from tests.units.conftest import DummyEntity, NullLogger


class DummyService(BaseService[DummyEntity]):
    pass


@pytest.fixture
def service(repo, logger):
    return DummyService(repo, logger, retention_days=None)


async def test_create_and_read(service):
    entity = await service.create(DummyEntity(name="x"))
    found = await service.read(entity.uuid)
    assert found is not None
    assert found.uuid == entity.uuid


async def test_update(service):
    entity = await service.create(DummyEntity(name="x"))
    updated = await service.update(entity.model_copy(update={"name": "y"}))
    assert updated.name == "y"
    assert updated.version == 2


async def test_soft_delete_hides_from_read(service):
    entity = await service.create(DummyEntity())
    await service.delete(entity.uuid)
    assert await service.read(entity.uuid) is None


async def test_find_all(service):
    await service.create(DummyEntity(name="a"))
    await service.create(DummyEntity(name="b"))
    result = await service.find_all()
    assert len(result) == 2


async def test_duplicate(service):
    entity = await service.create(DummyEntity(name="original"))
    clone = await service.duplicate(entity.uuid)
    assert clone.uuid != entity.uuid
    assert clone.name == "original"


async def test_read_unknown_returns_none(service):
    assert await service.read(uuid7()) is None


async def test_purge_with_zero_retention(repo, logger):
    service = DummyService(repo, logger, retention_days=0)
    entity = await service.create(DummyEntity())
    deleted = entity.model_copy(update={"deleted_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
    await repo.update(deleted)
    count = await service.purge()
    assert count == 1


async def test_purge_skipped_with_none_retention(repo, logger):
    service = DummyService(repo, logger, retention_days=None)
    entity = await service.create(DummyEntity())
    await repo.update(entity.model_copy(update={"deleted_at": datetime.now(timezone.utc)}))
    count = await service.purge()
    assert count == 0


def repo_from_service(service: DummyService) -> InMemoryRepository:
    return service._find_all._repository


