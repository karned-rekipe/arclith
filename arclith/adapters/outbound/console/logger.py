import sys
from typing import Any

from loguru import logger as loguru_logger

from arclith.domain.ports.outbound.logger import Logger, LogLevel
from arclith.domain.ports.outbound.observability import (
    CorrelationContextPort,
    LogRecordPort,
)

_LEVEL_EMOJI = {
    "DEBUG": "🔬",
    "INFO": "💬",
    "WARNING": "⚠️",
    "ERROR": "❌",
    "CRITICAL": "🔥",
}

_FORMAT = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | {extra[level_emoji]} <level>{level: <8}</level> | <level>{message}</level> | {extra[meta]}"

loguru_logger.remove()
loguru_logger.add(sys.stderr, format=_FORMAT)


class ConsoleLogger(Logger):
    def __init__(
        self,
        correlation: CorrelationContextPort | None = None,
        log_records: LogRecordPort | None = None,
    ) -> None:
        self._correlation = correlation
        self._log_records = log_records

    def configure_observability(
        self,
        correlation: CorrelationContextPort,
        log_records: LogRecordPort,
    ) -> None:
        self._correlation = correlation
        self._log_records = log_records

    def log(self, level: LogLevel, message: str, **metadata: Any) -> None:
        emoji = _LEVEL_EMOJI.get(level.value, "💬")
        correlation = dict(self._correlation.current()) if self._correlation else {}
        attributes = {**metadata, **correlation}
        bound = loguru_logger.bind(level_emoji=emoji, meta=attributes)
        getattr(bound, level.value.lower())(message)
        if self._log_records is not None:
            self._log_records.emit(level.value, message, attributes=attributes)
