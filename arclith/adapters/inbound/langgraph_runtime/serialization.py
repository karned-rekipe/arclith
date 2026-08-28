from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder


def jsonable(value: Any) -> Any:
    return jsonable_encoder(
        value,
        custom_encoder={
            datetime: lambda item: item.isoformat(),
            date: lambda item: item.isoformat(),
            UUID: str,
            Path: str,
            Enum: lambda item: item.value,
        },
    )


def snapshot_to_dict(snapshot: Any) -> dict[str, Any]:
    return {
        "values": jsonable(snapshot.values),
        "next": list(snapshot.next),
        "tasks": jsonable(list(snapshot.tasks)),
        "metadata": jsonable(snapshot.metadata),
        "created_at": snapshot.created_at,
        "checkpoint": _checkpoint(snapshot.config),
        "parent_checkpoint": _checkpoint(snapshot.parent_config),
    }


def sse_event(event: str, data: Any) -> bytes:
    encoded = json.dumps(jsonable(data), ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {encoded}\n\n".encode()


def safe_error(error: BaseException) -> dict[str, str]:
    return {
        "error": error.__class__.__name__,
        "message": str(error)[:1000],
    }


def _checkpoint(config: Any) -> dict[str, Any] | None:
    if not isinstance(config, Mapping):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, Mapping):
        return None
    return {
        str(key): jsonable(value)
        for key, value in configurable.items()
        if value is not None
    }
