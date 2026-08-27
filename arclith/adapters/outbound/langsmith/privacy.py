from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any


def trace_payload(value: object | None, *, enabled: bool) -> dict[str, Any]:
    if not enabled or value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): _safe_value(item) for key, item in value.items()}
    return {"value": _safe_value(value)}


def trace_metadata(
    value: Mapping[str, object] | None,
    *,
    enabled: bool,
) -> dict[str, Any]:
    if not enabled or value is None:
        return {}
    return {str(key): _safe_value(item) for key, item in value.items()}


def _safe_value(value: object) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, bytes | bytearray | memoryview):
        return "<binary omitted>"
    if isinstance(value, Mapping):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_safe_value(item) for item in value]
    return _safe_object(value)


def _safe_object(value: object) -> Any:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _safe_value(model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return _safe_value(asdict(value))
    return str(value)
