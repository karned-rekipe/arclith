import uuid as stdlib_uuid
from datetime import datetime, timezone

from uuid import UUID

from uuid6 import uuid7

from tests.units.conftest import DummyEntity


def test_default_uuid_is_uuid6():
    e = DummyEntity()
    assert isinstance(e.uuid, UUID)


def test_uuid_from_string():
    uid = str(uuid7())
    e = DummyEntity(uuid = uid)  # type: ignore[arg-type]  — tests the field_validator str coercion
    assert isinstance(e.uuid, UUID)
    assert str(e.uuid) == uid


def test_uuid_coerced_from_stdlib_uuid():
    uid = uuid7()
    std = stdlib_uuid.UUID(str(uid))
    e = DummyEntity(uuid=std)
    assert isinstance(e.uuid, UUID)
    assert str(e.uuid) == str(uid)


def test_is_deleted_false_by_default():
    assert not DummyEntity().is_deleted


def test_is_deleted_true_when_deleted_at_set():
    e = DummyEntity(deleted_at=datetime.now(timezone.utc))
    assert e.is_deleted


def test_version_default():
    assert DummyEntity().version == 1


def test_created_at_and_updated_at_are_aware():
    e = DummyEntity()
    assert isinstance(e.created_at, datetime)
    assert isinstance(e.updated_at, datetime)
    assert e.created_at.tzinfo is not None


def test_optional_fields_default_to_none():
    e = DummyEntity()
    assert e.created_by is None
    assert e.updated_by is None
    assert e.deleted_at is None
    assert e.deleted_by is None


def test_model_copy_preserves_type():
    e = DummyEntity(name="a")
    copy = e.model_copy(update={"name": "b"})
    assert isinstance(copy, DummyEntity)
    assert copy.uuid == e.uuid
    assert copy.name == "b"


def test_uuid_passthrough_when_already_uuid6():
    uid = uuid7()
    e = DummyEntity(uuid = uid)
    assert e.uuid is uid
