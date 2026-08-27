from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from arclith.domain.ports.outbound.observability import LogRecordPort

_RESERVED = frozenset(
    {
        "args",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    }
)


class OpenTelemetryLogRecordAdapter(LogRecordPort):
    """Emit OTLP records explicitly without installing a root logger handler."""

    def __init__(
        self,
        *,
        ensure_started: Callable[[], None],
        handler: Callable[[], logging.Handler | None],
        enabled: Callable[[], bool],
    ) -> None:
        self._ensure_started = ensure_started
        self._handler = handler
        self._enabled = enabled

    def emit(
        self,
        level: str,
        body: str,
        *,
        attributes: Mapping[str, object] | None = None,
    ) -> None:
        if not self._enabled():
            return
        self._ensure_started()
        handler = self._handler()
        if handler is None:
            return
        levelno = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        record = logging.LogRecord(
            "arclith",
            levelno,
            "",
            0,
            body,
            (),
            None,
        )
        for raw_key, value in (attributes or {}).items():
            key = str(raw_key).replace(".", "_")[:128]
            if key in _RESERVED or _is_sensitive(key):
                continue
            if isinstance(value, (str, bool, int, float)):
                setattr(record, key, value[:512] if isinstance(value, str) else value)
        handler.emit(record)


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(
        fragment in lowered
        for fragment in (
            "authorization",
            "body",
            "content",
            "cookie",
            "password",
            "payload",
            "prompt",
            "secret",
            "token",
        )
    )
