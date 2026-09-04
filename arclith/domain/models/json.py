from __future__ import annotations

import math

from pydantic import JsonValue


def validate_finite_json(value: JsonValue) -> JsonValue:
    """Reject non-finite numbers that Python accepts but JSON does not."""

    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON numeric values must be finite")
    if isinstance(value, list):
        for item in value:
            validate_finite_json(item)
    elif isinstance(value, dict):
        for item in value.values():
            validate_finite_json(item)
    return value
