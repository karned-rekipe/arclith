from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any


class CommandHandler(ABC):
    """Application command handler invoked by inbound command-bus adapters."""

    command_type: str

    @abstractmethod
    async def handle(self, payload: Mapping[str, Any], headers: Mapping[str, str]) -> None:
        """Validate a transport DTO, then invoke the matching use case."""
        raise NotImplementedError
