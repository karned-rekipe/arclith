from datetime import datetime, timezone

from arclith.application.use_cases.create import CreateUseCase
from tests.units.conftest import DummyEntity


async def test_create_stores_entity(repo, logger):
    uc = CreateUseCase(repo, logger)
    entity = DummyEntity(name="foo")
    result = await uc.execute(entity)
    assert result.uuid == entity.uuid
    assert await repo.read(result.uuid) is not None


async def test_create_sets_timestamps(repo, logger):
    before = datetime.now(timezone.utc)
    result = await CreateUseCase(repo, logger).execute(DummyEntity())
    assert result.created_at >= before
    assert result.updated_at >= before


async def test_create_returns_entity(repo, logger):
    entity = DummyEntity(name="bar")
    result = await CreateUseCase(repo, logger).execute(entity)
    assert result.name == "bar"
