from datetime import datetime, timezone

import pytest
from uuid6 import uuid7

from arclith.adapters.outbound.memory.repository import InMemoryRepository
from tests.units.conftest import DummyEntity


async def test_create_and_read(repo):
    e = DummyEntity(name="a")
    await repo.create(e)
    found = await repo.read(e.uuid)
    assert found is not None
    assert found.name == "a"


async def test_read_unknown_returns_none(repo):
    assert await repo.read(uuid7()) is None


async def test_update(repo):
    e = await repo.create(DummyEntity(name="a"))
    await repo.update(e.model_copy(update={"name": "b"}))
    assert (await repo.read(e.uuid)).name == "b"


async def test_delete_removes_from_store(repo):
    e = await repo.create(DummyEntity())
    await repo.delete(e.uuid)
    assert await repo.read(e.uuid) is None


async def test_delete_unknown_is_noop(repo):
    await repo.delete(uuid7())


async def test_find_all_excludes_deleted(repo):
    active = await repo.create(DummyEntity(name="active"))
    deleted = DummyEntity(name="deleted", deleted_at=datetime.now(timezone.utc))
    await repo.create(deleted)
    result = await repo.find_all()
    assert len(result) == 1
    assert result[0].name == "active"


async def test_find_all_empty(repo):
    assert await repo.find_all() == []


async def test_find_deleted(repo):
    e = DummyEntity(deleted_at=datetime.now(timezone.utc))
    await repo.create(e)
    await repo.create(DummyEntity(name="active"))
    result = await repo.find_deleted()
    assert len(result) == 1
    assert result[0].uuid == e.uuid


async def test_duplicate_assigns_new_uuid(repo):
    e = await repo.create(DummyEntity(name="original"))
    clone = await repo.duplicate(e.uuid)
    assert clone.uuid != e.uuid
    assert clone.name == "original"
    assert await repo.read(clone.uuid) is not None


async def test_duplicate_not_found_raises(repo):
    with pytest.raises(KeyError):
        await repo.duplicate(uuid7())


async def test_duplicate_deleted_raises(repo):
    e = DummyEntity(deleted_at=datetime.now(timezone.utc))
    await repo.create(e)
    with pytest.raises(KeyError):
        await repo.duplicate(e.uuid)

