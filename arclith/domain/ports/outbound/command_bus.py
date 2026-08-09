from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any


class CommandPublisher(ABC):
    """Outbound port for publishing application commands to a command bus."""

    @abstractmethod
    async def publish(
        self,
        command_type: str,
        payload: Mapping[str, Any],
        *,
        headers: Mapping[str, str] | None = None,
        routing_key: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        ...
