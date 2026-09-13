"""Canonical content shared by append-only store implementations."""

import hashlib
import json
import math
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, JsonValue

from arclith.domain.models.immutable_record import ImmutableRecord
from arclith.domain.ports.outbound.append_only_store import AppendOnlyError

_MAX_CANONICAL_DEPTH = 64


def record_fingerprint(record: ImmutableRecord) -> str:
    """Hash every declared field except the store-owned receipt timestamp.

    Read validated values directly: presentation serializers, aliases and field
    exclusions must never hide changed content from idempotency checks.
    """
    content = {
        name: _json_value(getattr(record, name), depth=0)
        for name in type(record).model_fields
        if name != "recorded_at"
    }
    content.update(
        (name, _json_value(value, depth=0))
        for name, value in (record.model_extra or {}).items()
    )
    payload = json.dumps(
        content,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _json_value(value: object, *, depth: int) -> JsonValue:
    if depth > _MAX_CANONICAL_DEPTH:
        raise AppendOnlyError("Record content exceeds the canonical nesting limit")
    if isinstance(value, Enum):
        return _json_value(value.value, depth=depth + 1)
    if isinstance(value, (list, tuple)):
        return [_json_value(item, depth=depth + 1) for item in value]
    if isinstance(value, BaseModel):
        fields = {name: getattr(value, name) for name in type(value).model_fields}
        fields.update(value.model_extra or {})
        return _json_value(fields, depth=depth + 1)
    if isinstance(value, dict):
        return _json_mapping(value, depth=depth)
    return _json_scalar(value)


def _json_mapping(value: dict[str, object], *, depth: int) -> JsonValue:
    if not all(isinstance(key, str) for key in value):
        raise AppendOnlyError("Record mappings must have string keys")
    return {key: _json_value(item, depth=depth + 1) for key, item in value.items()}


def _json_scalar(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise AppendOnlyError("Record datetimes must be timezone-aware")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, (date, UUID)):
        return str(value)
    if isinstance(value, Decimal) and value.is_finite():
        return str(value)
    raise AppendOnlyError("Record content contains an unsupported canonical value")
