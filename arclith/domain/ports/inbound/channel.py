from __future__ import annotations

from abc import ABC, abstractmethod

from arclith.domain.models.channel import (
    ChannelHandlerResult,
    ChannelIncomingMessage,
    ResolvedChannelIdentity,
)


class ChannelMessageHandler(ABC):
    """Application port invoked after channel normalization and identity mapping."""

    @abstractmethod
    async def handle(
        self,
        message: ChannelIncomingMessage,
        identity: ResolvedChannelIdentity,
    ) -> ChannelHandlerResult:
        """Invoke application use cases without depending on a provider SDK."""
        raise NotImplementedError
