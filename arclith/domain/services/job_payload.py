"""Bounded canonical job data, without serializers that can hide fields."""

import json
import math

from pydantic import BaseModel, JsonValue

MAX_JOB_PAYLOAD_BYTES = 65_536


def payload_content(value: object, *, depth: int = 0) -> JsonValue:
    """Accept JSON-native fields and nested models, rejecting SDK/secret objects."""
    if depth > 32:
        raise ValueError("Job data exceeds the nesting limit")
    if isinstance(value, BaseModel):
        fields = {name: getattr(value, name) for name in type(value).model_fields}
        fields.update(value.model_extra or {})
        return payload_content(fields, depth=depth + 1)
    if isinstance(value, dict):
        return _payload_mapping(value, depth=depth)
    if isinstance(value, (tuple, list)):
        return [payload_content(item, depth=depth + 1) for item in value]
    return _payload_scalar(value)


def _payload_mapping(value: dict[str, object], *, depth: int) -> JsonValue:
    if not all(isinstance(key, str) for key in value):
        raise ValueError("Job data mappings must have string keys")
    return {key: payload_content(item, depth=depth + 1) for key, item in value.items()}


def _payload_scalar(value: object) -> JsonValue:
    if value is None or (
        isinstance(value, (str, bool, int)) and type(value) in {str, bool, int}
    ):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError(
        "Job data must contain only JSON-native values and Pydantic models"
    )


def payload_json(value: object) -> str:
    content = json.dumps(
        payload_content(value), allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    if len(content.encode("utf-8")) > MAX_JOB_PAYLOAD_BYTES:
        raise ValueError(
            "Job request/result exceeds 64 KiB; use an external storage reference"
        )
    return content


def snapshot_payload[PayloadT: BaseModel](
    value: PayloadT, model: type[PayloadT]
) -> PayloadT:
    if type(value) is not model:
        raise ValueError("Job payload must match the store's declared model exactly")
    # Field exclusions, custom serializers and aliases cannot hide idempotency data.
    snapshot = model.model_validate_json(
        payload_json(value), strict=True, by_name=True, by_alias=False
    )
    # Validators may normalize or enrich data; validate the actual stored values.
    payload_json(snapshot)
    return snapshot
