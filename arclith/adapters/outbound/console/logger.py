import sys
from typing import Any

from loguru import logger as loguru_logger

from arclith.domain.ports.outbound.logger import Logger, LogLevel

_LEVEL_EMOJI = {
    "DEBUG": "🔬",
    "INFO": "💬",
    "WARNING": "⚠️",
    "ERROR": "❌",
    "CRITICAL": "🔥",
}

_FORMAT = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | {extra[level_emoji]} <level>{level: <8}</level> | <level>{message}</level> | {extra[meta]}"

loguru_logger.remove()
loguru_logger.add(sys.stderr, format = _FORMAT)


class ConsoleLogger(Logger):
    def log(self, level: LogLevel, message: str, **metadata: Any) -> None:
        emoji = _LEVEL_EMOJI.get(level.value, "💬")
        bound = loguru_logger.bind(level_emoji = emoji, meta = metadata)
        getattr(bound, level.value.lower())(message)
