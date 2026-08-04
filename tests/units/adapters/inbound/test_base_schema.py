import uuid as stdlib_uuid
from datetime import datetime, timezone

from uuid6 import uuid7

from arclith.adapters.inbound.schemas.base_schema import BaseSchema


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _base(**kwargs) -> dict:
    return {"uuid": str(uuid7()), "created_at": _now(), "updated_at": _now(), **kwargs}


def test_base_schema_from_dict():
    s = BaseSchema(**_base())
    assert s.version == 1
    assert s.is_deleted is False


def test_coerce_uuid_from_uuid6():
    uid = uuid7()
    s = BaseSchema(**_base(uuid = uid))
    assert str(s.uuid) == str(uid)


def test_coerce_uuid_from_stdlib_uuid():
    uid = stdlib_uuid.UUID(str(uuid7()))
    s = BaseSchema(**_base(uuid = uid))
    assert str(s.uuid) == str(uid)


def test_is_deleted_false_by_default():
    s = BaseSchema(**_base())
    assert s.is_deleted is False


def test_is_deleted_true_when_set():
    s = BaseSchema(**_base(is_deleted = True))
    assert s.is_deleted is True


def test_from_attributes_config():
    assert BaseSchema.model_config.get("from_attributes") is True
