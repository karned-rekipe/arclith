from uuid6 import uuid7

from arclith.application.use_cases.create import CreateUseCase
from arclith.application.use_cases.delete import DeleteUseCase
from arclith.application.use_cases.read import ReadUseCase
from tests.units.conftest import DummyEntity


async def test_read_existing(repo, logger):
    entity = await CreateUseCase(repo, logger).execute(DummyEntity())
    result = await ReadUseCase(repo, logger).execute(entity.uuid)
    assert result is not None
    assert result.uuid == entity.uuid


async def test_read_not_found(repo, logger):
    result = await ReadUseCase(repo, logger).execute(uuid7())
    assert result is None


async def test_read_deleted_returns_none(repo, logger):
    entity = await CreateUseCase(repo, logger).execute(DummyEntity())
    await DeleteUseCase(repo, logger).execute(entity.uuid)
    result = await ReadUseCase(repo, logger).execute(entity.uuid)
    assert result is None
