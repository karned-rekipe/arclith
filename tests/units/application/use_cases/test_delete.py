from uuid6 import uuid7

from arclith.application.use_cases.create import CreateUseCase
from arclith.application.use_cases.delete import DeleteUseCase
from tests.units.conftest import DummyEntity


async def test_soft_delete_sets_deleted_at(repo, logger):
    entity = await CreateUseCase(repo, logger).execute(DummyEntity())
    await DeleteUseCase(repo, logger).execute(entity.uuid)
    stored = await repo.read(entity.uuid)
    assert stored is not None
    assert stored.is_deleted


async def test_soft_delete_sets_deleted_by(repo, logger):
    entity = await CreateUseCase(repo, logger).execute(DummyEntity())
    await DeleteUseCase(repo, logger).execute(entity.uuid, deleted_by="user_1")
    stored = await repo.read(entity.uuid)
    assert stored.deleted_by == "user_1"


async def test_hard_delete_removes_entity(repo, logger):
    entity = await CreateUseCase(repo, logger).execute(DummyEntity())
    await DeleteUseCase(repo, logger, retention_days=0).execute(entity.uuid)
    assert await repo.read(entity.uuid) is None


async def test_delete_unknown_uuid_is_noop(repo, logger):
    await DeleteUseCase(repo, logger).execute(uuid7())
